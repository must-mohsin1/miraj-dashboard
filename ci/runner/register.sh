#!/usr/bin/env bash
set -euo pipefail

: "${RUNNER_TOKEN:?RUNNER_TOKEN is required for the one-time registration container}"
: "${RUNNER_URL:=https://github.com/must-mohsin1/miraj-dashboard}"
: "${RUNNER_NAME:=miraj-vps-ci}"
: "${RUNNER_LABELS:=miraj-ci}"

if [[ -f /runner/.runner ]]; then
  echo "Runner is already registered."
  exit 0
fi

./config.sh \
  --unattended \
  --url "$RUNNER_URL" \
  --token "$RUNNER_TOKEN" \
  --name "$RUNNER_NAME" \
  --labels "$RUNNER_LABELS" \
  --work _work \
  --replace
