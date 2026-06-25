#!/usr/bin/env python3
"""
omni_skill_eval.py — the deterministic gate behind the `omni-skill-eval` required check.

Backs omni-operator-learning v1.3 STEP 3 / omni-config §19 PATCH_AUTOMERGE_POLICY.
Runs on every `claude/skill-patch-*` PR. Its job is NOT to judge whether a patch is a
"good idea" (that is the learning loop's evidence gate: occ>=3 + eval history). Its job is
to be the deterministic BRAKE that makes Tier-1 auto-merge safe:

  1. The patched SKILL.md is structurally valid (frontmatter, description<=1024, no
     conflict markers / truncation, balanced code fences).
  2. The skill version actually increased vs the base branch.
  3. The patch did NOT strip or weaken a guardrail / governance line (anti-regression).
  4. A PR labelled `automerge:eligible` obeys the §19 Tier-1 envelope (1 skill file,
     <=40 changed lines, NOT touching a PROTECTED file/content) — defense in depth, so a
     buggy classify_tier can never push an oversized or protected change through auto-merge.

Exit 0 = check green (auto-merge may proceed if labelled eligible).
Exit 1 = check red (PR stays open for a human regardless of label).

Pure stdlib except PyYAML (installed in the workflow). No network, no LLM, reproducible.
"""
from __future__ import annotations
import os, re, sys, subprocess, fnmatch

# ── Constants MIRRORED from omni-config §19. Keep in sync on any §19 edit. ──────────────
MAX_DESC_CHARS      = 1024
TIER1_MAX_LINES     = 40
TIER1_MAX_FILES     = 1
SKILLS_GLOB         = "skills/*/SKILL.md"
PROTECTED_PATCH_FILES = [
    "skills/omni-config/*",
    "skills/omni-utils/*",
    "skills/omni-orchestrator/*",
    "*governance*", "*VN-GOV*",
    ".github/workflows/*",
]
PROTECTED_PATCH_CONTENT = ["yilun", "andrea", "vn-gov", "capacity", "sow",
                           "scope governance", "autonomy boundary", "governance guard",
                           "branch safety"]
# Guardrail markers whose deletion is treated as weakening the constitution.
GUARDRAIL_MARKERS = ["NON-NEGOTIABLE", "NEVER", "MUST NEVER", "\u26d4"]  # \u26d4 = ⛔

BASE = os.environ.get("BASE_SHA", "origin/main")
HEAD = os.environ.get("HEAD_SHA", "HEAD")
AUTOMERGE = os.environ.get("AUTOMERGE_LABEL", "false").lower() == "true"

fails: list[str] = []
warns: list[str] = []


def sh(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True).stdout


def changed_files() -> list[str]:
    out = sh("git", "diff", "--name-only", f"{BASE}...{HEAD}")
    return [f.strip() for f in out.splitlines() if f.strip()]


def is_protected(path: str) -> bool:
    return any(fnmatch.fnmatch(path, g) for g in PROTECTED_PATCH_FILES)


def parse_frontmatter(text: str) -> dict | None:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    try:
        import yaml
        return yaml.safe_load(m.group(1)) or {}
    except Exception as e:                       # pragma: no cover
        fails.append(f"frontmatter YAML did not parse: {e}")
        return {}


def base_version(path: str) -> str | None:
    text = sh("git", "show", f"{BASE}:{path}")
    if not text:
        return None
    fm = parse_frontmatter(text)
    return str(fm.get("version")) if fm else None


def vtuple(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "0"))


def removed_lines(path: str) -> list[str]:
    """Lines deleted by the patch (diff '-' lines, excluding the '---' file header)."""
    diff = sh("git", "diff", "--unified=0", f"{BASE}...{HEAD}", "--", path)
    out = []
    for ln in diff.splitlines():
        if ln.startswith("-") and not ln.startswith("---"):
            out.append(ln[1:])
    return out


def changed_line_count(path: str) -> int:
    diff = sh("git", "diff", "--unified=0", f"{BASE}...{HEAD}", "--", path)
    add = sum(1 for ln in diff.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
    rem = sum(1 for ln in diff.splitlines() if ln.startswith("-") and not ln.startswith("---"))
    return add + rem


def validate_skill_file(path: str) -> None:
    try:
        text = open(path, encoding="utf-8").read()
    except FileNotFoundError:
        fails.append(f"{path}: deleted by patch (skill deletion never auto-merges)")
        return

    # 1. structure
    if any(mk in text for mk in ("<<<<<<<", "=======\n", ">>>>>>>")):
        fails.append(f"{path}: unresolved merge-conflict markers")
    if text.count("```") % 2 != 0:
        fails.append(f"{path}: unbalanced ``` code fences ({text.count('```')})")
    if not text.endswith("\n"):
        warns.append(f"{path}: missing trailing newline (possible truncation)")

    fm = parse_frontmatter(text)
    if fm is None:
        fails.append(f"{path}: missing YAML frontmatter")
        return
    for key in ("name", "version", "description"):
        if not fm.get(key):
            fails.append(f"{path}: frontmatter missing '{key}'")
    desc = str(fm.get("description", ""))
    if len(desc) > MAX_DESC_CHARS:
        fails.append(f"{path}: description {len(desc)} chars > {MAX_DESC_CHARS} (§ skill-edit rule)")

    # 2. version must increase vs base
    bv = base_version(path)
    nv = str(fm.get("version", ""))
    if bv is not None and vtuple(nv) <= vtuple(bv):
        fails.append(f"{path}: version not bumped (base {bv} -> head {nv})")

    # 3. anti-guardrail-stripping (the core safety net)
    for rl in removed_lines(path):
        low = rl.lower()
        if any(tok in low for tok in PROTECTED_PATCH_CONTENT):
            fails.append(f"{path}: patch DELETES a governance/protected line -> {rl.strip()[:80]!r}")
        if any(mk in rl for mk in GUARDRAIL_MARKERS):
            fails.append(f"{path}: patch DELETES a guardrail line -> {rl.strip()[:80]!r}")


def main() -> int:
    files = changed_files()
    if not files:
        print("omni-skill-eval: no changed files — nothing to validate.")
        return 0

    skill_files = [f for f in files if fnmatch.fnmatch(f, SKILLS_GLOB)]
    protected_hits = [f for f in files if is_protected(f)]

    # Validate every changed skill file structurally + for guardrail stripping.
    for f in skill_files:
        validate_skill_file(f)

    # 4. §19 Tier-1 envelope enforcement — ONLY binds PRs asking to auto-merge.
    if AUTOMERGE:
        if protected_hits:
            fails.append(f"automerge:eligible but touches PROTECTED path(s): {protected_hits} "
                         f"-> must be Tier-2 (needs-human)")
        if len(skill_files) > TIER1_MAX_FILES or len(files) > TIER1_MAX_FILES:
            fails.append(f"automerge:eligible but changes {len(files)} files (Tier-1 max {TIER1_MAX_FILES})")
        for f in skill_files:
            n = changed_line_count(f)
            if n > TIER1_MAX_LINES:
                fails.append(f"automerge:eligible but {f} has {n} changed lines (Tier-1 max {TIER1_MAX_LINES})")
        # content-level protection across the whole diff
        full = sh("git", "diff", f"{BASE}...{HEAD}")
        if any(tok in full.lower() for tok in PROTECTED_PATCH_CONTENT):
            warns.append("automerge:eligible PR diff mentions governance/protected tokens — "
                         "verify it is not weakening them (deletions already hard-fail above)")

    # ── report ──
    label = "automerge:eligible" if AUTOMERGE else "needs-human"
    print(f"omni-skill-eval | label={label} | files={len(files)} | skill_files={len(skill_files)}")
    for w in warns:
        print(f"  ::warning:: {w}")
    if fails:
        for x in fails:
            print(f"  ::error:: {x}")
        print(f"\nRESULT: FAIL ({len(fails)} blocking issue(s)). PR stays open for human review.")
        return 1
    print("\nRESULT: PASS. Structurally valid, version bumped, no guardrail/governance regression.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
