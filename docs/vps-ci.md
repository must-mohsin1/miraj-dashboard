# VPS CI

Miraj uses a repository-scoped GitHub Actions runner hosted in an isolated
Docker container on the VPS. Self-hosted jobs do not consume GitHub-hosted
runner minutes.

## Security boundary

The repository is public, so `.github/workflows/vps-ci.yml` intentionally runs
only for pushes to branches in the main repository and manual dispatches. Do
not add `pull_request` or `pull_request_target`: fork code must never execute on
the production-adjacent VPS.

The runner container has:

- no production source, database, environment, or Docker socket mounts;
- read-only repository permissions through `GITHUB_TOKEN`;
- no published ports or inbound listener;
- all Linux capabilities dropped and `no-new-privileges` enabled;
- a 1.25 CPU, 3 GB memory, and 512 PID ceiling.

## Provision or rebuild

Copy `ci/runner/` to a dedicated VPS directory, then build it:

```bash
cd ~/miraj-ci-runner
docker compose -f compose.yml build --pull runner
```

Create a short-lived repository registration token from an authenticated admin
machine. Pass it only to the one-time registration container; do not save it in
a file or Compose environment:

```bash
REGISTRATION_TOKEN="$(gh api \
  -X POST \
  repos/must-mohsin1/miraj-dashboard/actions/runners/registration-token \
  -q .token)"

printf '%s\n' "$REGISTRATION_TOKEN" | ssh mohsin@187.127.112.15 '
  read -r RUNNER_TOKEN
  export RUNNER_TOKEN
  cd ~/miraj-ci-runner
  docker compose -f compose.yml run --rm -e RUNNER_TOKEN runner register.sh
'
unset REGISTRATION_TOKEN
```

Start the registered runner:

```bash
cd ~/miraj-ci-runner
docker compose -f compose.yml up -d runner
docker compose -f compose.yml ps
```

The registration token expires quickly and the one-time container is removed.
The runner's repository-scoped identity remains in the `runner-data` volume.

## CI scope

Each push runs:

1. deterministic backend, analysis-core, and dashboard Python suites;
2. all frontend Jest tests;
3. the Next.js production build.

The Python script explicitly lists nine known non-deterministic or stale legacy
cases as deselected. Their names remain visible in CI output and in
`scripts/ci_python_tests.sh` until repaired.

## Operations

```bash
cd ~/miraj-ci-runner
docker compose -f compose.yml ps
docker compose -f compose.yml logs --tail=100 runner
docker stats --no-stream miraj-ci-runner
```

The runner auto-updates itself. Rebuild the image periodically to refresh the
pinned Node base image, OS packages, and bundled runner version.
