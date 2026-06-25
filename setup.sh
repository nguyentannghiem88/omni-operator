#!/usr/bin/env bash
# OMNI Operator — environment staging for Claude Code Routines.
# Safe to run at the start of every routine run. Idempotent.
set -u
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1) Stage skills where every OMNI skill expects to find its siblings.
mkdir -p /mnt/skills/user 2>/dev/null \
  && cp -r "$REPO_ROOT/skills/." /mnt/skills/user/ 2>/dev/null \
  && echo "OK: skills staged to /mnt/skills/user ($(ls -1 /mnt/skills/user | wc -l) skills)" \
  || echo "WARN: could not stage to /mnt/skills/user (will fall back to repo paths)"

# 2) Materialize the ADO PAT from the secret env var into the file the ADO skills read.
mkdir -p /mnt/project 2>/dev/null || true
if [ "${ADO_PAT:-}" != "" ]; then
  printf '%s' "$ADO_PAT" > /mnt/project/ado_pat.txt && echo "OK: ADO PAT written"
else
  echo "NOTE: ADO_PAT not set — ADO sync steps will be skipped this run."
fi

# 3) Best-effort Python deps (most work is done via MCP connectors, so this rarely matters).
pip install --quiet --break-system-packages requests python-dateutil 2>/dev/null || true

# 4) Authenticate gh so the Monday learning run can open claude/ skill-patch PRs.
if [ "${GH_TOKEN:-}" != "" ]; then
  echo "$GH_TOKEN" | gh auth login --with-token 2>/dev/null \
    && echo "OK: gh authenticated" || echo "WARN: gh auth failed"
else
  echo "NOTE: GH_TOKEN not set — skill-patch PRs skipped this run."
fi
echo "OMNI staging complete."
