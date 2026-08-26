#!/usr/bin/env bash
set -u

run_id="${1:?usage: watch_campaign.sh RUN_ID CAMPAIGN_INPUT [RUN_ROOT]}"
campaign_input="${2:?usage: watch_campaign.sh RUN_ID CAMPAIGN_INPUT [RUN_ROOT]}"
run_root="${3:-runs/$run_id}"
health_url="${E2B_API_URL:-https://e2b.fact-lab.work}/health"
log_path="$run_root/watch.log"

mkdir -p "$run_root"

while true; do
  http_code="$(curl -sS -o "$run_root/e2b-health.txt" -w '%{http_code}' --max-time 15 "$health_url" 2>/dev/null || true)"
  printf '%s e2b_health=%s\n' "$(date -Iseconds)" "${http_code:-000}" >> "$log_path"

  if [[ "$http_code" == "200" ]]; then
    PYTHONPATH=src ./lda --root "$run_root" run \
      --flow argus-humanize \
      --run-id "$run_id" \
      --campaign-input "$campaign_input" >> "$log_path" 2>&1
    exit_code=$?
    printf '%s lda_exit=%s\n' "$(date -Iseconds)" "$exit_code" >> "$log_path"
    if [[ "$exit_code" -eq 0 ]]; then
      exit 0
    fi
  fi

  sleep 30
done
