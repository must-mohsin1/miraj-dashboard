
## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
- Author a backlog-ready spec/issue → invoke /spec

## Design System
Always read DESIGN.md before making any visual or UI decisions.
All font choices, colors, spacing, and aesthetic direction are defined there.
Do not deviate without explicit user approval.
In QA mode, flag any code that doesn't match DESIGN.md.

## Deploy Configuration

- **Platform:** Custom VPS (Docker Compose)
- **Production URL:** https://ta.munafaplus.pk
- **SSH:** `mohsin@187.127.112.15` path `~/miraj-dashboard`
- **Deploy steps after merge to `main`:**
  1. `ssh mohsin@187.127.112.15`
  2. `cd ~/miraj-dashboard && git pull --ff-only origin main`
  3. `export SQLITE_DATA_DIR=./.runtime/sqlite` (or source `.env`)
  4. `docker compose build web nextjs` (include `monitor` if backend worker changed)
  5. `docker compose up -d web nextjs`
  6. Health: `curl -sf http://127.0.0.1:8010/health`
- **GitHub:** Create/merge PRs as **`must-mohsin1`** only.
  - Before PR/merge: `gh auth switch --user must-mohsin1 && gh api user -q .login`
  - Prefer REST merge if GraphQL times out:  
    `gh api repos/must-mohsin1/miraj-dashboard/pulls/N/merge -X PUT -f merge_method=squash`
  - Avoid `--delete-branch` when local `main` is locked to another worktree.
- **Canary:** `curl -sS -o /dev/null -w "%{http_code}\n" https://ta.munafaplus.pk/` (expect 200). Optional deeper check: portfolio + journal routes.
- **No GitHub Actions deploy workflow** — production is VPS-only.
