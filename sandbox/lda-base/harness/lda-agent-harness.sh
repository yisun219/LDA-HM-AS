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
session_dir=/opt/lda/agent-state/sessions
trace_dir=/opt/lda/agent-state/traces
mkdir -p "$session_dir" "$trace_dir"

backend="${LDA_AGENT_BACKEND:-}"
if test -z "$backend"; then
  if test -n "${ANTHROPIC_API_KEY:-}${ANTHROPIC_AUTH_TOKEN:-}"; then
    backend=claude
  elif test -s /home/user/.codex/auth.json && test "$(wc -c </home/user/.codex/auth.json)" -gt 2; then
    backend=codex
  else
    backend=pi
  fi
fi

if test "$backend" = claude; then
  command -v claude >/dev/null || { echo "claude agent CLI is not installed" >&2; exit 69; }
  thread_file="$session_dir/$session.thread"
  raw_trace="$trace_dir/$session.jsonl"
  last_message="$session_dir/$session.last.txt"
  model_args=(--model "${LDA_AGENT_MODEL:-claude-opus-4-8}")
  effort_args=(--effort "${LDA_AGENT_THINKING:-high}")
  common_args=(
    --print --bare --output-format json
    --add-dir /opt/lda/control /opt/lda/skills
    "${model_args[@]}" "${effort_args[@]}"
  )
  case "$role" in
    analyst|drafter|planner)
      role_args=(--tools Read,Grep,Glob --allowed-tools Read,Grep,Glob --permission-mode dontAsk)
      ;;
    reviewer)
      common_args+=(--add-dir /opt/lda/review)
      role_args=(--tools Read,Grep,Glob --allowed-tools Read,Grep,Glob --permission-mode dontAsk)
      ;;
    builder)
      role_args=(
        --tools Bash,Edit,Write,Read,Grep,Glob
        --allowed-tools Bash,Edit,Write,Read,Grep,Glob
        --permission-mode dontAsk
      )
      ;;
    *) echo "unknown role: $role" >&2; exit 64 ;;
  esac
  if test -s "$thread_file"; then
    claude "${common_args[@]}" "${role_args[@]}" \
      --resume "$(cat "$thread_file")" "$(cat "$prompt_file")" >"$raw_trace"
  else
    claude "${common_args[@]}" "${role_args[@]}" \
      "$(cat "$prompt_file")" >"$raw_trace"
    thread_id="$(jq -er '.session_id' "$raw_trace")"
    printf '%s\n' "$thread_id" >"$thread_file"
  fi
  jq -er '.result' "$raw_trace" >"$last_message"
  test -s "$last_message"
  cat "$last_message"
  exit 0
fi

if test "$backend" = codex; then
  command -v codex >/dev/null || { echo "codex agent CLI is not installed" >&2; exit 69; }
  thread_file="$session_dir/$session.thread"
  raw_trace="$trace_dir/$session.jsonl"
  last_message="$session_dir/$session.last.txt"
  model_args=()
  test -z "${LDA_AGENT_MODEL:-}" || model_args=(--model "$LDA_AGENT_MODEL")
  if test -s "$thread_file"; then
    thread_id="$(cat "$thread_file")"
    codex exec resume --json "${model_args[@]}" \
      --output-last-message "$last_message" \
      "$thread_id" "$(cat "$prompt_file")" >"$raw_trace"
  else
    sandbox_mode=read-only
    test "$role" = builder && sandbox_mode=workspace-write
    codex exec --json --sandbox "$sandbox_mode" --cd /opt/lda/work \
      --skip-git-repo-check "${model_args[@]}" \
      --output-last-message "$last_message" \
      "$(cat "$prompt_file")" >"$raw_trace"
    thread_id="$(jq -r 'select(.type == "thread.started") | .thread_id' "$raw_trace" | head -1)"
    test -n "$thread_id" && test "$thread_id" != null
    printf '%s\n' "$thread_id" >"$thread_file"
  fi
  test -s "$last_message"
  cat "$last_message"
  exit 0
fi

test "$backend" = pi || { echo "unsupported Agent backend: $backend" >&2; exit 64; }
command -v pi >/dev/null || { echo "pi agent CLI is not installed" >&2; exit 69; }

provider_args=()
model_args=()
thinking_args=(--thinking "${LDA_AGENT_THINKING:-high}")
test -z "${LDA_AGENT_PROVIDER:-}" || provider_args=(--provider "$LDA_AGENT_PROVIDER")
test -z "${LDA_AGENT_MODEL:-}" || model_args=(--model "$LDA_AGENT_MODEL")

tool_args=()
case "$role" in
  analyst|reviewer) tool_args=(--tools read,grep,find,ls) ;;
  drafter|planner) tool_args=(--tools read,grep,find,ls) ;;
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
