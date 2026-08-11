#!/usr/bin/env bash
set -euo pipefail

if [[ ! -x /runner/bin/Runner.Listener ]]; then
  cp -a /opt/actions-runner/. /runner/
fi

cd /runner
exec "$@"
