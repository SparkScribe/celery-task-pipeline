#!/usr/bin/env bash
# End-to-end smoke test: submit process_data job and poll until succeeded.
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
MAX_POLLS="${MAX_POLLS:-30}"
POLL_INTERVAL="${POLL_INTERVAL:-2}"

echo "Waiting for API health at ${API_URL}/health..."
for _ in $(seq 1 "${MAX_POLLS}"); do
  if curl -sf "${API_URL}/health" >/dev/null; then
    break
  fi
  sleep "${POLL_INTERVAL}"
done

if ! curl -sf "${API_URL}/health" >/dev/null; then
  echo "API health check failed"
  exit 1
fi

echo "Submitting process_data job..."
CREATE_RESPONSE="$(curl -sf -X POST "${API_URL}/api/v1/jobs" \
  -H "Content-Type: application/json" \
  -d '{"task_type":"process_data","payload":{"input_text":"ci smoke test","delay_seconds":0}}')"

JOB_ID="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' <<<"${CREATE_RESPONSE}")"
echo "Created job ${JOB_ID}"

for _ in $(seq 1 "${MAX_POLLS}"); do
  JOB_RESPONSE="$(curl -sf "${API_URL}/api/v1/jobs/${JOB_ID}")"
  STATUS="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])' <<<"${JOB_RESPONSE}")"
  echo "Poll status: ${STATUS}"
  if [[ "${STATUS}" == "succeeded" ]]; then
    echo "${JOB_RESPONSE}" | python3 -m json.tool
    exit 0
  fi
  if [[ "${STATUS}" == "failed" ]]; then
    echo "Job failed:"
    echo "${JOB_RESPONSE}" | python3 -m json.tool
    exit 1
  fi
  sleep "${POLL_INTERVAL}"
done

echo "Timed out waiting for job ${JOB_ID} to succeed"
exit 1
