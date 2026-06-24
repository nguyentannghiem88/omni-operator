---
name: omni-operator-learning
version: "1.2"
description: "Closed learning loop for the OMNI AI Operator. Aggregates operator_eval_reviews + operator_feedback over a 14-day window, promotes recurring issues (≥2 occurrences) to durable operator_rule facts injected into briefing/EOD, audits skill version drift, and proposes SKILL.md patches for human approval. Also defines the in-chat feedback capture convention. v1.2: STEP 1C Recall Mining (Loop v3) — scores RECALL (materialized incidents/blockers flagged ahead vs missed) mined from raw source_items+risks, merges a recall block into the calibration fact, and promotes vigilance-only 'flag earlier' rules for recurring misses (≥2×). Triggers on: 'run operator learning', 'learning review', 'weekly learning', 'promote lessons', 'train the operator', 'self-improve', 'audit skill drift'. Run weekly (Mondays) or on demand."
---

# OMNI Operator Learning — v1.2

**Purpose:** Make the AI Operator self-improving. Converts eval findings and user
corrections into (a) durable prevention rules auto-injected into every briefing/EOD run,
and (b) proposed SKILL.md patches exported for Nghiem's approval.

```
Output → Eval (eval-review) → Feedback (capture rule) → Aggregate (this skill)
       → Promote operator_rule → Inject (briefing/EOD STEP 0A2) → Patch skills (human-approved)
```

---

## ⚠️ READ FIRST — SHARED CONFIG + UTILS

1. `/mnt/skills/user/omni-config/SKILL.md` → constants (CONFIG_VERSION = "1.11", §10 + §10B)
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
SKILL_VERSION = "1.2"
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

## STEP 3 — PROPOSE SKILL PATCHES (human-in-the-loop)

For each rule with `occurrences >= 3` OR `severity >= 8` AND a clear `target_skill`:

1. Read the target SKILL.md, locate `target_step`.
2. Draft a minimal patch (changed-section diff only) that hard-codes the rule into
   the skill — making the rule structural, not just injected.
3. Apply patch to a COPY in `/home/claude/`, export to
   `/mnt/user-data/outputs/<skill>-SKILL.md`, and call `present_files`.
4. Show the diff summary FIRST; Nghiem approves and re-uploads — `/mnt/skills/user/`
   is read-only at runtime, so this is the only patch path.
5. On approval confirmation in a later session: set rule `status_note='patched_into_skill'`
   and bump the skill version in omni-config §10 registry (export updated config too).

Never patch more than 3 skills per learning run. Never patch omni-utils/omni-config
without explicit confirmation.

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
    summary=f"Learning run — {n_signals} signals → {n_promoted} rules promoted, {n_merged} merged, {n_patches} patches proposed, drift: {n_drift}",
    metadata={"signals": n_signals, "promoted": n_promoted, "merged": n_merged,
              "patches_proposed": patch_list, "drift": drift_list,
              "score_trend": score_series},
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

## Skill patches proposed (<N>)
- <skill> <vX → vY>: <1-line change> → exported for approval

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

- ⛔ Never modify `/mnt/skills/user/` directly — read-only; patches go via outputs export.
- ⛔ Never auto-apply a patch without showing the diff and getting approval.
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
| v1.2 | **Loop v3 — recall mining (learn from misses)** (2026-06-23). New STEP 1C scores RECALL, the blind spot Loop v2 left open: detects materialized incident/blocker events from raw `source_items` (urgency/tags/keyword heuristic), matches each to its earliest prior `risks` flag (market+module / ≥2-token overlap / feature_key), and classifies flagged-ahead (lead ≥`LEARNING_RECALL_LEAD_MIN_DAYS`=1d) vs late vs missed → `recall = ahead/(ahead+late+missed)` with trend vs prior. Recurring missed clusters (≥2× same market/feature) promote `category="risk"` "flag earlier" rules via STEP 2 — vigilance-only, never gate/weaken/governance. Recall block merged into the same daily `calibration` fact (one extra upsert; no new fact_type/table). STEP 5 gains a Recall line + Top-missed section. Mined independent of the sparse `outcome_signal` pipeline, so it works immediately. STEP 1C.1 excludes governance/capacity/SOW items (hardened by a live dry-run that mis-caught a "Mongo SOW cost" item as an incident). Handshake → config 1.11 (registers learning 1.2 + adds §10B `LEARNING_RECALL_LEAD_MIN_DAYS`). |
| v1.1 | **Loop v2 — calibration + rule decay (Gate 3)** (2026-06-14). New STEP 1B reads `outcome_signal` facts (from omni-data-sync v12.3) → computes ranking_precision / over_rate / under_rate / risk_hit_rate with trend vs prior, writes `calibration` fact (180d). New STEP 2B rule decay: autonomous staleness-archive (non-gov, sev<8, >45d unreinforced), high-sev stale PROPOSED only, effectiveness `review` flag from degrading calibration. ⛔ Hard governance guard (never archive/propose VN-GOV/gov rules). Output gains Calibration line + Rule decay section. Handshake bumped to utils v11.2 / config v1.8. Requires omni-data-sync v12.3 emitting outcome_signal. |
| v1.0 | Initial. Feedback capture convention, 14d aggregation, ≥2× rule promotion to knowledge_facts(operator_rule), briefing/EOD injection contract (STEP 0A2), human-approved skill patch pipeline, version drift audit vs omni-config §10, trend reporting, hygiene expiry. |
