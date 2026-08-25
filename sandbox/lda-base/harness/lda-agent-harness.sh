#!/usr/bin/env bash
set -euo pipefail

prompt_file=""
role=""
session=""
while (($#)); do
  case "$1" in
    --prompt-file) prompt_file="$2"; shift 2 ;;
    --role) role="$2"; shift 2 ;;
    --session) session="$2"; shift 2 ;;
    *) echo "unknown harness argument: $1" >&2; exit 64 ;;
  esac
done

test "${LDA_EXECUTION_MODE:-e2b}" = e2b || { echo "LDA refuses non-E2B execution" >&2; exit 78; }
test -s "$prompt_file" || { echo "prompt file is required" >&2; exit 64; }
test -n "$role" && test -n "$session" || { echo "role and session are required" >&2; exit 64; }
command -v pi >/dev/null || { echo "pi agent CLI is not installed" >&2; exit 69; }

session_dir=/opt/lda/work/.lda-hm/sessions
trace_dir=/opt/lda/work/.lda-hm/traces
mkdir -p "$session_dir" "$trace_dir"

provider_args=()
model_args=()
thinking_args=(--thinking "${LDA_AGENT_THINKING:-high}")
test -z "${LDA_AGENT_PROVIDER:-}" || provider_args=(--provider "$LDA_AGENT_PROVIDER")
test -z "${LDA_AGENT_MODEL:-}" || model_args=(--model "$LDA_AGENT_MODEL")

tool_args=()
case "$role" in
  analyst|reviewer) tool_args=(--tools read,bash,grep,find,ls) ;;
  drafter|planner) tool_args=(--tools read,write,bash,grep,find,ls) ;;
  builder) tool_args=() ;;
  *) echo "unknown role: $role" >&2; exit 64 ;;
esac

prompt=$(cat "$prompt_file")
pi --print --approve \
  --session-id "$session" --session-dir "$session_dir" \
  --skill /opt/lda/skills \
  "${provider_args[@]}" "${model_args[@]}" "${thinking_args[@]}" "${tool_args[@]}" \
  "$prompt"

latest=$(find "$session_dir" -type f -name '*.jsonl' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
test -n "$latest" && cp "$latest" "$trace_dir/$session.jsonl"
