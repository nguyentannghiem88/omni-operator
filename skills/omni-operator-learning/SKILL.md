---
name: omni-operator-learning
version: "1.2"
description: "Closed learning loop for the OMNI AI Operator. Aggregates operator_eval_reviews + operator_feedback over a 14-day window, promotes recurring issues (≥2 occurrences) to durable operator_rule facts injected into briefing/EOD, audits skill version drift, scores recall of materialized incidents, and turns high-confidence rules into git-native skill-patch PRs. Defines the in-chat feedback capture convention. v1.3: STEP 3 git-native tiered auto-merge per §19 PATCH_AUTOMERGE_POLICY — opens claude/ skill-patch PRs; Tier-1 (single non-protected skill, ≤40 lines, occ≥3) auto-merges on a green omni-skill-eval check; Tier-2 (omni-utils/omni-config/omni-orchestrator/governance/multi-file) and the registry-bump PR stay human-merge; circuit breaker forces Tier-2 after 2 degrading eval trends; Cowork export fallback preserved. Triggers on: 'run operator learning', 'learning review', 'weekly learning', 'promote lessons', 'train the operator', 'self-improve', 'audit skill drift'. Run weekly (Mondays) or on demand."
---

# OMNI Operator Learning — v1.3

**Purpose:** Make the AI Operator self-improving. Converts eval findings and user
corrections into (a) durable prevention rules auto-injected into every briefing/EOD run,
and (b) proposed SKILL.md patches exported for Nghiem's approval.

```
Output → Eval (eval-review) → Feedback (capture rule) → Aggregate (this skill)
       → Promote operator_rule → Inject (briefing/EOD STEP 0A2) → Patch skills (human-approved)
```

---

## ⚠️ READ FIRST — SHARED CONFIG + UTILS

1. `/mnt/skills/user/omni-config/SKILL.md` → constants (CONFIG_VERSION = "1.13", §10 + §10B + §19 PATCH_AUTOMERGE_POLICY)
2. `/mnt/skills/user/omni-utils/SKILL.md` → utilities (UTILITY_VERSION = "11.2")

⛔ Mem0 is retired. Supabase only. No new tables — uses `knowledge_facts`,
`operator_eval_reviews`, `actions`.

---

## STORAGE CONTRACT (knowledge_facts)

| fact_type | fact_key | Content | Expiry |
|---|---|---|---|
| `operator_feedback` | `fb:<YYYYMMDD>:<slug>` | One user correction (see capture rule) | 90d |
| `operator_rule` | `rule:<category>:<slug>` | Promoted prevention rule | none |
| `outcome_signal` | `out:<kind>:<ref>` | READ — terminal action/risk vs prediction (from omni-data-sync v12.3 STEP 7A0) | 120d |
| `calibration` | `calibration:operator:<date>` | WRITE — weekly precision metrics + trend | 180d |

`operator_rule` content schema:
```json
{
  "instruction": "<imperative rule applied at briefing/EOD STEP 0A2, ≤40 words>",
  "category": "<ranking|reply_detection|decision_class|governance|risk|tone|drafting|sync|other>",
  "severity": 1-10,
  "occurrences": N,
  "evidence": ["eval:<review_date>:<check_n>", "fb:<fact_key>"],
  "target_skill": "<skill name or null>",
  "target_step": "<STEP ref or null>",
  "promoted_at": "<YYYY-MM-DD>",
  "status_note": "<active|patched_into_skill>"
}
```

---

## FEEDBACK CAPTURE CONVENTION (always-on, all conversations)

Whenever Nghiem corrects AI Operator output in chat — wrong priority, missed action,
wrong tone, wrong owner/date, wrong classification, bad draft — the operator MUST,
silently and immediately:

```python
upsert_knowledge_fact("operator_feedback", f"fb:{today}:{slug}", {
    "correction": "<what Nghiem said was wrong, ≤40 words>",
    "expected":   "<what the correct behavior was, ≤40 words>",
    "context":    "<skill/output that produced the mistake>",
    "category":   "<same taxonomy as operator_rule>",
    "captured_at": now_str,
})
```

Confirm with one line only: `📝 Feedback captured for learning loop.`
Do NOT capture: preference statements already in user_preferences, one-off data
corrections (fix those in the source table directly), or stylistic chatter.

---

## STEP 0 — BOOTSTRAP + VERSION DRIFT AUDIT

```python
SKILL_VERSION = "1.3"
# 1. Load EXPECTED_SKILL_VERSIONS from omni-config §10
# 2. For each skill dir in /mnt/skills/user/: read frontmatter/header version
# 3. drift = [s for s in skills if on_disk_version != expected_version]
```

Report drift table (skill | on-disk | expected). Drift items become P1 findings —
stale skills are the #1 cause of recurring eval failures.

---

## STEP 1 — AGGREGATE SIGNALS (last LEARNING_LOOKBACK_DAYS = 14)

```sql
-- Eval findings (live schema: run_date, jsonb columns)
SELECT run_date, score, findings, missed_actions, decision_review,
       reply_required_review, risk_review, recommended_fixes
FROM operator_eval_reviews
WHERE run_date >= CURRENT_DATE - INTERVAL '14 days'
ORDER BY run_date;

-- Feedback
SELECT fact_key, content FROM knowledge_facts
WHERE fact_type = 'operator_feedback' AND status = 'active'
  AND updated_at >= NOW() - INTERVAL '14 days';

-- Existing rules (for dedup/merge)
SELECT fact_key, content FROM knowledge_facts
WHERE fact_type = 'operator_rule' AND status = 'active';
```

Normalize every eval finding and feedback item into:
`{category, description, evidence_ref, severity, date}`.
Cluster by (category + semantic similarity of description). Two items describing the
same failure mode = one cluster with `occurrences = 2`.

---

## STEP 1B — OUTCOME CALIBRATION ⭐ v1.1 (Loop v2)

Read the `outcome_signal` facts emitted by omni-data-sync STEP 7A0 over the window and
score how well the operator's PREDICTIONS matched reality. This is the PRECISION side of
the loop; recall (risks that occurred but were never flagged) is out of scope v2.0.

```sql
SELECT content FROM knowledge_facts
WHERE fact_type = 'outcome_signal' AND status = 'active'
  AND updated_at >= NOW() - INTERVAL '14 days';
```

```python
rows = [r["content"] for r in supabase_sql(_outcome_query) or []]
def rate(n, d): return round(n / d, 2) if d else None

acts = [r for r in rows if r.get("kind") == "action"]
rsk  = [r for r in rows if r.get("kind") == "risk"]
hi = sum(1 for r in acts if r["verdict"] == "hit")
ov = sum(1 for r in acts if r["verdict"] == "over")
un = sum(1 for r in acts if r["verdict"] == "under")
risk_hits = sum(1 for r in rsk if r.get("materialized") is True)

cal = {
    "window_days": 14, "n_actions": len(acts), "n_risks": len(rsk),
    "ranking_precision": rate(hi, hi + ov),   # of high-ranked closed items, share actually actioned
    "over_rate":  rate(ov, len(acts)),        # cry-wolf: ranked high, never needed
    "under_rate": rate(un, len(acts)),        # missed urgency: low item became a blocker
    "risk_hit_rate": rate(risk_hits, len(rsk)),
    "computed_at": now_str,
}

# Trend vs the most recent prior calibration snapshot
prior = supabase_sql("""SELECT content FROM knowledge_facts
  WHERE fact_type='calibration' AND status='active'
  ORDER BY updated_at DESC LIMIT 1;""") or []
prev = prior[0]["content"] if prior else {}
def trend(curr, prv, lower_is_better=False):
    if prv is None or curr is None: return "n/a"
    d = curr - prv
    if abs(d) < 0.05: return "flat"
    good = (d < 0) if lower_is_better else (d > 0)
    return "improving" if good else "degrading"
cal["trend"] = {
    "ranking_precision": trend(cal["ranking_precision"], prev.get("ranking_precision")),
    "over_rate":         trend(cal["over_rate"],  prev.get("over_rate"),  lower_is_better=True),
    "under_rate":        trend(cal["under_rate"], prev.get("under_rate"), lower_is_better=True),
}

upsert_knowledge_fact("calibration", f"calibration:operator:{today}", cal,
    scope="global", source_skill="omni-operator-learning",
    expires_at=(now + timedelta(days=180)).isoformat())
```

`cal` feeds STEP 2B (rule decay) and the STEP 5 output. A category whose metric is
`degrading` means its current rules are NOT working — list them for review.

---

## STEP 1C — RECALL MINING ⭐ v1.2 (Loop v3 — learn from MISSES)

STEP 1B scores PRECISION (of what we flagged, how much mattered). This step scores RECALL:
of the incidents/blockers that actually MATERIALIZED, how many did the operator flag *ahead*
of time vs miss entirely. Recall is the blind spot Loop v2 left open. Mined from raw
`source_items` + `risks` — independent of the (still-sparse) `outcome_signal` pipeline, so it
works even before precision telemetry accrues.

⚠️ Heuristic by necessity: `risks` has no "materialized" flag and `source_items` has no
signal-type column. Incidents are detected by urgency/tags/keywords and matched to prior flags
fuzzily. Two guardrails keep false positives harmless: the ≥2× promotion gate, and the fact
that recall rules only ever ADD vigilance ("flag earlier") — a recall rule can never weaken or
gate anything, so a wrong one costs a little noise, never a governance breach.

```python
LEAD_MIN_DAYS = 1   # → omni-config §10B LEARNING_RECALL_LEAD_MIN_DAYS; <1 day warning = "late", not "ahead"
```

### 1C.1 — Pull materialized incident/blocker events (window)
```sql
SELECT id, feature_key, market, module, title, summary, priority, is_urgent,
       tags, source_tags, item_created_at
FROM source_items
WHERE item_created_at >= now() - (INTERVAL '1 day' * %(window)s)   -- window = LEARNING_LOOKBACK_DAYS
  AND (
    is_urgent = true
    OR lower(coalesce(priority,'')) = 'urgent'
    OR EXISTS (SELECT 1 FROM unnest(coalesce(tags,'{}') || coalesce(source_tags,'{}')) t
               WHERE lower(t) = ANY (ARRAY['incident','blocker','urgent','p1','outage','prod-down','regression']))
    OR lower(coalesce(title,'') || ' ' || coalesce(summary,'')) ~
       '(incident|prod(uction)? down|outage|\mp1\M|blocker|broke|broken|regression|rollback|cutover fail)'
  )
  -- Exclude governance/capacity/SOW items — they are NOT incidents and recall logic must never
  -- brush against governance topics. (Hardened 2026-06-23 after a live dry-run mis-caught a
  -- "Mongo SOW cost" governance item as an incident.)
  AND NOT (
    lower(coalesce(title,'') || ' ' || coalesce(summary,'')) ~
    '(\msow\M|capacity|\mfte\M|budget|invoice|rate basis|\mscope\M|estimate|mongo)'
  )
ORDER BY item_created_at;
```

### 1C.2 — Pull candidate prior flags (risks, reaching 30d before the window so lead-time is measurable)
```sql
SELECT risk_key, title, description, market, module, severity,
       coalesce(first_seen::timestamptz, created_at) AS flagged_at
FROM risks
WHERE coalesce(first_seen::timestamptz, created_at) >= now() - (INTERVAL '1 day' * (%(window)s + 30));
```

### 1C.3 — Match each event to its earliest prior flag (python)
```python
import re
def toks(s): return set(re.findall(r"[a-z0-9]{4,}", (s or "").lower()))
STOP = {"prod","production","issue","error","incident","please","need","ticket","update"}

def earliest_prior_flag(ev, risks):
    et = ev["item_created_at"]
    ev_tok = (toks(ev["title"]) | toks(ev["summary"])) - STOP
    found = []
    for r in risks:
        if r["flagged_at"] >= et:                       # a flag must PRECEDE the event
            continue
        same_mm = (r["market"] and r["market"] == ev["market"]
                   and r["module"] and r["module"] == ev["module"])
        overlap = (toks(r["title"]) | toks(r["description"])) & ev_tok
        fk_hit  = bool(ev.get("feature_key")) and \
                  ev["feature_key"].split(":")[-1] in ((r["title"] or "") + " " + (r["description"] or "")).lower()
        if same_mm or len(overlap) >= 2 or fk_hit:
            found.append(r["flagged_at"])
    return min(found) if found else None

ahead = late = missed = 0
missed_events = []
for ev in incidents:                                    # from 1C.1
    f = earliest_prior_flag(ev, risk_flags)             # from 1C.2
    if f is None:
        missed += 1; missed_events.append(ev)
    else:
        lead = (ev["item_created_at"].date() - f.date()).days
        if lead >= LEAD_MIN_DAYS: ahead += 1
        else:                     late  += 1

n_ev   = ahead + late + missed
recall = round(ahead / n_ev, 2) if n_ev else None
```

### 1C.4 — Cluster the MISSES (recurring → flag-earlier rule candidates)
```python
from collections import Counter
def cluster_key(ev):
    # Cluster on the canonical entity. feature_key already IS the entity, so use it directly —
    # a single noun token splits "Medusa star calculation" from "Medusa star calc broke" apart.
    if ev.get("feature_key"):
        return ev["feature_key"]
    return f'{ev.get("market") or "?"}:{ev.get("module") or "?"}'

clusters = Counter(cluster_key(e) for e in missed_events)
recall_miss_clusters = [{"key": k, "count": c} for k, c in clusters.items()
                        if c >= LEARNING_RULE_PROMOTION_MIN_OCCURRENCES]    # ≥2 → STEP 2
```

### 1C.5 — Recall block + trend, merged into today's calibration fact
```python
prior_recall = (prev or {}).get("recall", {})           # prev = prior calibration content (from STEP 1B)
def trend_up(curr, prv):                                 # higher recall = better
    if prv is None or curr is None: return "n/a"
    d = curr - prv
    return "flat" if abs(d) < 0.05 else ("improving" if d > 0 else "degrading")

recall_block = {
    "window_days": LEARNING_LOOKBACK_DAYS, "n_materialized": n_ev,
    "flagged_ahead": ahead, "late": late, "missed": missed,
    "recall": recall, "trend": trend_up(recall, prior_recall.get("recall")),
    "top_missed": [c["key"] for c in recall_miss_clusters], "computed_at": now_str,
}
# Re-upsert the SAME calibration fact written in 1B, now enriched with recall (one extra upsert/run).
upsert_knowledge_fact("calibration", f"calibration:operator:{today}", {**cal, "recall": recall_block},
    scope="global", source_skill="omni-operator-learning",
    expires_at=(now + timedelta(days=180)).isoformat())
```

`recall_miss_clusters` feed STEP 2 as recall rule candidates. A `degrading` recall trend means
the operator is missing MORE incidents than before — surface it prominently in STEP 5.

---

## STEP 2 — PROMOTE RULES

For each cluster with `occurrences >= LEARNING_RULE_PROMOTION_MIN_OCCURRENCES` (2):

1. If a matching `operator_rule` exists → MERGE: increment `occurrences`, extend
   `evidence`, raise `severity` if warranted, update `promoted_at`.
2. Else → write new rule via `upsert_knowledge_fact("operator_rule", key, content)`.
3. Write the rule `instruction` as a single imperative sentence the briefing/EOD can
   apply directly. Bad: "decision classification was wrong". Good: "Treat any decision
   lacking explicit confirmation language from the decision-maker as PENDING, never
   CONFIRMED."
4. **Recall clusters (v1.2):** for each `recall_miss_clusters` item (≥2 unflagged incidents
   sharing market/feature), promote a `category="risk"` rule that ADDS vigilance — e.g.
   "When a signal mentions `<keyword>` for `<market>`, flag it `at_risk` on first sighting:
   it preceded N unflagged incidents in 14d." Evidence = the missed event ids. These rules
   only ever increase caution; they NEVER gate, weaken, or alter governance routing.

Cap: if active rules > LEARNING_MAX_ACTIVE_RULES (25) → set lowest-severity,
lowest-occurrence rules to `status='archived'` (valid per knowledge_facts status CHECK).

Single-occurrence clusters: keep as feedback, do NOT promote. List them in output
as "watching (1×)".

---

## STEP 2B — RULE DECAY ⭐ v1.1 (Loop v2)

Retire dead weight so the injected rule set stays sharp.

**A. Staleness (autonomous, reversible).** A rule not reinforced this run (no matching
cluster) AND older than DECAY_DAYS (45) AND `severity < 8` AND NOT governance →
`status='archived'`. High-severity stale rules are PROPOSED for retire, never
auto-archived (rare-but-critical rules can stay quiet for weeks).

**B. Effectiveness (surfaced, human-judged).** Using STEP 1B calibration: if a rule's
category metric is `degrading` while the rule is active, it isn't helping (or is wrong)
— flag `effectiveness='review'` and list it. No auto-archive (cannot prove causation
without firing telemetry).

```python
from datetime import date, datetime, timedelta
DECAY_DAYS = 45   # → omni-config §10B LEARNING_RULE_DECAY_DAYS
PROTECTED  = ("governance",)
GOV_TERMS  = ("vn-gov", "andrea", "yilun", "capacity", "sow", "scope governance", "peter", "ha hoang")

reinforced = {c["rule_key"] for c in promoted_or_merged_this_run}   # from STEP 2
archived, proposed_retire, review, protected = [], [], [], []

for rule in active_rules:                 # existing-rules read from STEP 1
    c = rule["content"]; key = rule["fact_key"]
    blob = (c.get("instruction","") + " " + str(c.get("category",""))).lower()
    is_gov = c.get("category") in PROTECTED or any(t in blob for t in GOV_TERMS)
    if is_gov:
        protected.append(key)             # HARD GUARD — never archive/propose governance
        continue
    try:    age = (date.today() - date.fromisoformat(str(c.get("promoted_at"))[:10])).days
    except Exception: age = 0
    stale = (key not in reinforced) and (age >= DECAY_DAYS)
    if stale and c.get("severity", 5) < 8:
        upsert_knowledge_fact("operator_rule", key, {**c, "status_note": "archived_stale"},
                              status="archived")
        archived.append(key)
    elif stale:
        proposed_retire.append(key)       # high-severity stale → propose only
    # effectiveness annotation from calibration trend
    deg = (c.get("category") == "ranking" and cal["trend"].get("over_rate") == "degrading") or \
          (c.get("category") == "risk" and cal.get("risk_hit_rate") == 0 and cal["n_risks"])
    if deg and key not in archived:
        upsert_knowledge_fact("operator_rule", key, {**c, "effectiveness": "review"})
        review.append(key)
```

⛔ Governance / VN-GOV rules are NEVER archived or proposed for retire — hard guarded
above. This preserves the constitution: learning may reinforce governance, never weaken it.

---

## STEP 3 — PATCH SKILLS (git-native, tiered auto-merge) ⭐ v1.3

Reads §19 `PATCH_*` from omni-config. Turns each high-confidence rule into a `claude/`-branch
PR. **Tier-1** PRs auto-merge on a green `omni-skill-eval` check; **Tier-2** PRs wait for
Nghiem. The loop NEVER pushes to `main` and NEVER auto-merges a protected/governance patch.

### 3.0 — Context + circuit breaker (gate before any patch)
```python
import os
from fnmatch import fnmatch
# Read §19 from omni-config: PATCH_REPO, PATCH_TIERS, PROTECTED_PATCH_FILES,
# PROTECTED_PATCH_CONTENT, PATCH_AUTOMERGE_POLICY, AUTOMERGE_ENABLED.
MODE = os.environ.get("OMNI_PATCH_MODE", "export")   # routine env sets "git"; else legacy export

# Circuit breaker: 2 consecutive degrading eval-score/recall trends → force every patch to Tier-2.
last2 = supabase_sql("""SELECT content FROM knowledge_facts
  WHERE fact_type='calibration' AND status='active'
  ORDER BY updated_at DESC LIMIT 2;""") or []
def _deg(c):
    t = c.get("trend", {}) or {}
    return t.get("ranking_precision") == "degrading" or (c.get("recall", {}) or {}).get("trend") == "degrading"
degrading2 = len(last2) == 2 and all(_deg(r["content"]) for r in last2)
automerge_live = AUTOMERGE_ENABLED and not degrading2
# If degrading2: open a needs-human config PR proposing AUTOMERGE_ENABLED=False (durable kill-switch)
# and surface it in STEP 5. This run is already safe (forced Tier-2 below).
```

### 3.1 — Select candidates (cap = weekly_automerge_cap, default 3)
Rules with `occurrences >= 3 OR severity >= 8`, a clear `target_skill` + `target_step`, and
`status_note='active'` (NOT already `patched_into_skill`). Max 3 per run.

### 3.2 — Draft the minimal patch
Read the target SKILL.md, locate `target_step`, draft the smallest changed-section edit that
hard-codes the rule (structural, not just injected). Compute `changed_lines`; `files=1` here.

### 3.3 — Classify tier (per §19 — this is the safety decision)
```python
def classify_tier(target_file, patch_text, rule, changed_lines, files=1):
    protected_file = any(fnmatch(target_file, g) for g in PROTECTED_PATCH_FILES)
    protected_text = any(t in patch_text.lower() for t in PROTECTED_PATCH_CONTENT)
    t1 = PATCH_TIERS["tier1_auto"]
    eligible = (automerge_live and not protected_file and not protected_text
                and files <= t1["max_files"] and changed_lines <= t1["max_changed_lines"]
                and rule["content"].get("occurrences", 0) >= 3)
    return "tier1" if eligible else "tier2"
```
A high-severity (sev≥8) but only-2× rule, anything touching a PROTECTED file/content, anything
over the diff caps, or a tripped circuit breaker → **Tier-2** (human merge). Default-safe.

### 3.4 — Open the PR
- **`export` mode** (Cowork / interactive, `/mnt/skills/user` read-only): write the patched copy
  to `/mnt/user-data/outputs/<skill>-SKILL.md`, `present_files`, show the diff summary FIRST,
  and STOP — identical to ≤v1.2. No git here; the next routine run (or Nghiem) opens the PR.
- **`git` mode** (routine: repo cloned, files writable, `gh` available):
```bash
git checkout -b claude/skill-patch-<skill>-<YYYYMMDD>
# edit skills/<skill>/SKILL.md in place, then:
git add skills/<skill>/SKILL.md
git commit -m "fix(<skill>): <rule.instruction first 60c> [operator-learning]"
git push -u origin HEAD
LABEL=<automerge:eligible | needs-human>     # from classify_tier
gh pr create --base main --label "$LABEL" \
     --title "skill-patch: <skill> — <1-line>" --body "<body>"
# Tier-1 ONLY — enable native auto-merge; GitHub merges when omni-skill-eval is green:
gh pr merge --auto --squash                  # Tier-2: OMIT — left for human merge
```
PR body MUST include: rule key + `evidence` refs, tier + reason, the changed-section diff, and
the companion-registry note (3.5). Branch safety (`claude/` prefix) stays ON at the routine env.

### 3.5 — Companion registry-bump PR (ALWAYS Tier-2 / needs-human)
A Tier-1 skill auto-merge bumps the skill's on-disk version, but `EXPECTED_SKILL_VERSIONS` lives
in omni-config (a PROTECTED file). Open a SEPARATE `needs-human` PR bumping §10 for that skill.
**The code fix ships automatically; the human ratifies the version ledger.** Until that PR
merges, the drift audit shows one expected row — a visible record that an auto-merge happened.

### 3.6 — On merge (this run or a later one)
When a patch PR is detected merged: set rule `status_note='patched_into_skill'`, record the merge
sha in `evidence`. Never patch the same rule twice. Never patch >3 skills/run. omni-utils /
omni-config / omni-orchestrator are PROTECTED → they are ALWAYS Tier-2, never auto-merged.

---

## STEP 4 — HYGIENE

```sql
-- Expire stale feedback (90d)
UPDATE knowledge_facts SET status = 'archived'   -- status CHECK allows: active|archived|resolved|closed
WHERE fact_type = 'operator_feedback'
  AND updated_at < NOW() - INTERVAL '90 days' AND status = 'active';
```

Also run `cleanup_stale_knowledge_facts()` from omni-utils if available.

---

## STEP 5 — LOG + OUTPUT

```python
write_action(
    skill="LEARNING", action_type="LEARNING_RUN",
    summary=f"Learning run — {n_signals} signals → {n_promoted} promoted, {n_merged} merged, "
            f"{n_patches} PRs ({n_automerge} auto / {n_human} needs-human), drift: {n_drift}",
    metadata={"signals": n_signals, "promoted": n_promoted, "merged": n_merged,
              "drift": drift_list, "score_trend": score_series,
              # §19 audit: link each patch rule → PR → merge outcome
              "patches": patch_list,            # [{rule_key, skill, tier, pr_url, label, merged}]
              "automerge_enabled": automerge_live, "circuit_breaker_tripped": degrading2},
)
```

### Output format (compact)

```
# OPERATOR LEARNING — <YYYY-MM-DD> (GMT+7)

Eval score trend (14d): <score series> → <improving|flat|degrading>
Calibration (14d): ranking_precision <x> (<trend>) | over_rate <x> (<trend>) | under_rate <x> (<trend>) | risk_hit_rate <x> | n=<actions>/<risks>
Recall (14d): <recall> (<trend>) | ahead <a> · late <l> · missed <m> of <n> materialized incidents

## Rules promoted/merged (<N>)
| Rule | Category | Occ | Sev | Source |
|---|---|---|---|---|

## Skill patches (<N>)  ⭐ v1.3
- 🟢 auto-merge (Tier-1, eval-gated): <skill> <vX→vY> — <1-line> → <pr_url> (<merged|awaiting eval>)
- 🟡 needs-human (Tier-2): <skill> <vX→vY> — <1-line> → <pr_url>
- ⚙️ registry-bump PRs (needs-human): <skill> §10 <vX→vY> → <pr_url>
- 🔴 circuit breaker: <"tripped — all patches forced Tier-2; config kill-switch PR opened" | omit>

## Rule decay (<N>)
- archived (stale, non-gov, sev<8): <keys>
- propose retire (stale, high-sev): <keys>
- review (calibration degrading): <keys>
- protected (governance — never touched): <count>

## Version drift (<N>)
| Skill | On-disk | Expected |

## Top missed — flag earlier (<N>)  ⭐ v1.2
- <market/feature> ×<count> → recall rule promoted (or "watching 1×" if below threshold)

## Watching (1× — not yet promoted)
- <item>

Next learning run: <next Monday>
```

---

## GUARDRAILS

- ⛔ Never push to `main` — branch safety ON; all changes via `claude/skill-patch-*` PRs.
- ⛔ Never auto-merge a Tier-2 / PROTECTED_PATCH_FILES / PROTECTED_PATCH_CONTENT patch, and
  never auto-merge without a green `omni-skill-eval` check. Tier-1 auto-merge is eval-gated only.
- ⛔ Never auto-merge `omni-utils` / `omni-config` / `omni-orchestrator` or any governance-touching
  patch — these are ALWAYS Tier-2 (human merge). The registry-bump PR is ALWAYS needs-human.
- Rules must be imperative, testable, ≤40 words. Vague rules are rejected.
- Never promote from a single occurrence (min 2) — avoids overfitting to one-off noise.
- Never write transient sync data to knowledge_facts — operator_feedback/operator_rule only.
- One learning run per week unless Nghiem explicitly triggers a re-run.
- Governance rules (YiLun routing, Andrea protocol) are constitution-level — learning
  may reinforce them but NEVER weaken or override them.

---

## TRIGGERS

`run operator learning` | `learning review` | `weekly learning` | `promote lessons` |
`train the operator` | `self-improve` | `audit skill drift`
Auto-suggested: when eval-review STEP 3F flags a recurring check failure.

---

## CHANGELOG

| Version | Change |
|---|---|
| v1.3 | **Git-native tiered auto-merge (2026-06-24).** STEP 3 rewritten from export-only "propose patch" to a git-native PR flow governed by omni-config §19 `PATCH_AUTOMERGE_POLICY`. New 3.0 reads §19 + a circuit breaker (2 consecutive degrading eval/recall trends → force all patches Tier-2 + open a needs-human config kill-switch PR). 3.3 `classify_tier`: Tier-1 = single non-protected skill, ≤40 changed lines / 1 file, occ≥3, auto-merge enabled → label `automerge:eligible` + `gh pr merge --auto` (merges only on a green `omni-skill-eval` check); everything else (PROTECTED files/content, sev-only rules, over-cap diffs, tripped breaker) → Tier-2 `needs-human`. 3.4 dual-mode: `git` (routine clone, writable, `gh`) opens the PR; `export` (Cowork, read-only mount) preserves the ≤v1.2 outputs-export + present_files fallback. 3.5 companion §10 registry-bump PR is ALWAYS needs-human — code fix ships auto, human ratifies the version ledger. STEP 5 audit logs `{rule_key, skill, tier, pr_url, label, merged}` + breaker state. Guardrails rewritten: never push main, never auto-merge Tier-2/protected/governance, never auto-merge without green eval. Config handshake → 1.13. Registers in §10 when this file ships. | New STEP 1C scores RECALL, the blind spot Loop v2 left open: detects materialized incident/blocker events from raw `source_items` (urgency/tags/keyword heuristic), matches each to its earliest prior `risks` flag (market+module / ≥2-token overlap / feature_key), and classifies flagged-ahead (lead ≥`LEARNING_RECALL_LEAD_MIN_DAYS`=1d) vs late vs missed → `recall = ahead/(ahead+late+missed)` with trend vs prior. Recurring missed clusters (≥2× same market/feature) promote `category="risk"` "flag earlier" rules via STEP 2 — vigilance-only, never gate/weaken/governance. Recall block merged into the same daily `calibration` fact (one extra upsert; no new fact_type/table). STEP 5 gains a Recall line + Top-missed section. Mined independent of the sparse `outcome_signal` pipeline, so it works immediately. STEP 1C.1 excludes governance/capacity/SOW items (hardened by a live dry-run that mis-caught a "Mongo SOW cost" item as an incident). Handshake → config 1.11 (registers learning 1.2 + adds §10B `LEARNING_RECALL_LEAD_MIN_DAYS`). |
| v1.1 | **Loop v2 — calibration + rule decay (Gate 3)** (2026-06-14). New STEP 1B reads `outcome_signal` facts (from omni-data-sync v12.3) → computes ranking_precision / over_rate / under_rate / risk_hit_rate with trend vs prior, writes `calibration` fact (180d). New STEP 2B rule decay: autonomous staleness-archive (non-gov, sev<8, >45d unreinforced), high-sev stale PROPOSED only, effectiveness `review` flag from degrading calibration. ⛔ Hard governance guard (never archive/propose VN-GOV/gov rules). Output gains Calibration line + Rule decay section. Handshake bumped to utils v11.2 / config v1.8. Requires omni-data-sync v12.3 emitting outcome_signal. |
| v1.0 | Initial. Feedback capture convention, 14d aggregation, ≥2× rule promotion to knowledge_facts(operator_rule), briefing/EOD injection contract (STEP 0A2), human-approved skill patch pipeline, version drift audit vs omni-config §10, trend reporting, hygiene expiry. |
