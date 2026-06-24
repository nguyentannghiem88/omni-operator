---
name: omni-self-improve
version: "1.2"
description: "Post-run auto-train hook for the OMNI AI Operator. Closes the fast BEHAVIORAL learning loop automatically after each briefing/EOD with no manual trigger: light inline-eval of the output just produced → promote ≥2× issue clusters to operator_rule (auto-applied at briefing/EOD STEP 0A2 next run) → drift audit (surface only) → flag structural patch candidates for omni-operator-learning. v1.2: STEP 2B weekly-gated reversible backlog auto-age — message-sourced actions (email/teams/comment) P1→P2 at 10d idle, non-client-facing P2→aged-stale at 21d, client-facing flagged stale_verify only; never touches clickup_task/ADO/calendar/governance; reversible via raw_json.autoage_run. Token-gated: stays silent when no new signal. NEVER edits SKILL.md files and NEVER weakens governance rules. Triggers automatically as the final step of omni-eod-review (P2) and omni-daily-briefing (P3); also on demand: 'self improve', 'run self-improve', 'auto-train', 'close the loop'."
---

# OMNI Self-Improve — v1.2

**Purpose:** Make the operator self-training without a manual trigger. After every
briefing/EOD, run the cheap half of the learning loop so behavioral fixes apply from
the very next run.

```
briefing/EOD output → [this hook] light inline-eval → promote ≥2× → operator_rule
                    → STEP 0A2 auto-applies it on the NEXT briefing/EOD (no human step)
```

## ⛔ AUTONOMY BOUNDARY (read first — non-negotiable)

| Tier | What it does | Autonomy |
|---|---|---|
| **Behavioral** | promote/merge `operator_rule`; rules auto-injected at STEP 0A2 | ✅ FULLY AUTONOMOUS |
| **Structural** | edit a SKILL.md step | ⛔ NEVER here — only *flagged*; drafted+exported by omni-operator-learning, re-uploaded by Nghiem |

`/mnt/skills/user/` is read-only at runtime. This skill **cannot and must not** rewrite
skill files. It changes *behavior* (rules), never *code*. Governance rules (YiLun→Andrea
routing, capacity protocol) are constitution-level — may be reinforced, NEVER weakened.

---

## ⚠️ READ FIRST — SHARED CONFIG + UTILS

1. `/mnt/skills/user/omni-config/SKILL.md` → `EXPECTED_SKILL_VERSIONS` (§10), `LEARNING_*` (§10B), CONFIG_VERSION = "1.6"
2. `/mnt/skills/user/omni-utils/SKILL.md` → `upsert_knowledge_fact()`, `write_action()`, `supabase_sql()`, UTILITY_VERSION = "11.1"

⛔ Mem0 retired. Supabase only. No new tables — uses `operator_eval_reviews`,
`knowledge_facts`, `actions`. No new columns.

---

## STEP 0 — BOOTSTRAP + TOKEN GATE

```python
SKILL_VERSION = "1.2"
# 0A. user_time_v0 → TODAY, now_str (+07)
# 0B. Read last self-improve cursor from actions (no new storage):
```
```sql
SELECT created_at, raw_json
FROM actions
WHERE action_type = 'SELF_IMPROVE_RUN'
ORDER BY created_at DESC LIMIT 1;          -- cursor = created_at, or epoch if none
```
```python
# 0C. GATE — is there new signal since cursor?
#   new_evals  = operator_eval_reviews.created_at > cursor
#   new_fb     = knowledge_facts(operator_feedback).updated_at > cursor
#   new_output = actions WHERE skill IN ('EOD','BRIEFING') AND action_type='REVIEWED'
#                AND created_at > cursor   (the briefing/EOD run that called us)
#                — NOTE: briefing/EOD log action_type='REVIEWED', NOT 'EOD_RUN'/'BRIEFING_RUN'
# If none of the three → OUTPUT "Self-improve: no new signal — loop idle." and STOP.
#   (Do not eval, do not promote, do not log a run. Idle is free.)
```

When called as a hook, `new_output` is true by construction; the gate mainly protects
on-demand re-runs from doing redundant work.

---

## STEP 1 — LIGHT INLINE EVAL (subset, not the full 15)

Evaluate ONLY the output the calling run just produced (top_actions / decisions /
risks / reply queue from `get_context_pack()` or the inline briefing/EOD text).
Run the 5 highest-leverage checks — full 15-check audit stays in `omni-ai-operator-eval-review`:

| # | Check | Flag |
|---|---|---|
| 1 | Source signal asked for action but no action exists | `MISSED_ACTION` |
| 2 | Decision `confirmed` without explicit source confirmation wording | `WRONG_CLASSIFICATION` P1 |
| 3 | Decision record missing any of {title,status,evidence} | `MISSING_DECISION_STATUS` |
| 4 | Direct stakeholder question with no reply-required action | `MISSING_REPLY_ACTION` |
| 5 | Context pack `degraded=true` or older than CACHE_DEAD_H | `STALE_CONTEXT` |

Write ONE record to `operator_eval_reviews` using the eval-review payload contract:
`review_type='on_demand'`, `evaluated_workflow='<caller>(self-improve)'`,
`created_by='self-improve'`, `summary` prefixed `[AUTO] `. `overall_status`: any P1→`critical`,
else issues→`issues_found`, else `pass`. Reuse eval-review STEP 3 dedupe (same
workflow + output date today → append-only rerun row, never overwrite).
If a check passes, mark PASS — never fabricate issues.

---

## STEP 2 — PROMOTE (delta window only — the autonomous fix)

Aggregate ONLY signals since cursor (not the full 14d — that's the weekly job):
this run's eval issues + new `operator_feedback`. Cluster by `(category + similar
description)`. For each cluster with `occurrences >= LEARNING_RULE_PROMOTION_MIN_OCCURRENCES` (2):

1. Matching `operator_rule` exists → MERGE (occurrences+1, extend evidence, raise severity).
2. Else → `upsert_knowledge_fact("operator_rule", "rule:<cat>:<slug>", content)` with the
   schema from omni-operator-learning (imperative `instruction` ≤40 words, testable).
3. Cap at `LEARNING_MAX_ACTIVE_RULES` (25) — archive lowest sev×occ if over.

⛔ Single-occurrence clusters are NEVER promoted — kept as feedback ("watching 1×").
This is the anti-overfit guardrail; one noisy run must not rewrite operator behavior.

Promoted rules need no further action — briefing/EOD STEP 0A2 loads active `operator_rule`
facts every run, so the fix is live on the next briefing/EOD automatically.

---

## STEP 2B — WEEKLY BACKLOG AUTO-AGE (gated, reversible) ⭐ v1.2

Message-sourced actions (email/teams/comment) have **no completion-detection path** — they
only accumulate and inflate P1/P2. This is the one bounded data-hygiene pass permitted here
(carve-out to the "hygiene belongs to operator-learning" guardrail), kept safe by being
**weekly-gated, reversible, and tightly scoped**. It changes operational data, never code.

**Weekly gate (mandatory — keeps the hook light):**
```python
# Only run once per 7 days, even though this hook fires after every briefing/EOD.
last_age = supabase_sql("""
  SELECT max((raw_json->>'autoage_run')) AS last_run
  FROM actions WHERE raw_json ? 'autoage_run';
""")[0]["last_run"]   # value form: 'autoage_YYYY-MM-DD'
# Parse date from last_age; if <7 days ago → SKIP STEP 2B entirely (print one idle line).
# Else proceed. autoage_run = f"autoage_{TODAY}".
```

**Scope & guardrails (NON-NEGOTIABLE):**
- ONLY `source IN ('email','sent_email','teams','teams_message','clickup_comment')`. NEVER
  `clickup_task` overdue/blocked, calendar prep, `ado_work_item`, or `req:*` — those are live work.
- NEVER governance/VN-GOV (`module='VN-GOV'` or `action_key ILIKE '%governance%'`) — must stay visible.
- Tier 1: open **P1** idle ≥10d → **P2**.
- Tier 2: open **non-client-facing P2** idle ≥21d → status **`aged-stale`** (closed).
- Client-facing stale P2 is **NEVER auto-closed** → flagged `raw_json.stale_verify=true`, left open.
- Reversible: status/priority + `raw_json` audit only, **NEVER deletes**. Idempotent (each
  downgrade resets `updated_at` → no double-jump in one run). Undo a run via
  `raw_json->>'autoage_run' = 'autoage_<date>'`.

```python
if run_step_2b:   # passed weekly gate
    age = supabase_sql(f"""
    WITH t1 AS (
      UPDATE actions SET priority='P2', updated_at=now(),
        raw_json = coalesce(raw_json,'{{}}'::jsonb) || jsonb_build_object(
          'downgraded_from','P1','autoage_tier',1,'autoage_reason','stale_msg_p1_gt10d','autoage_run','{autoage_run}')
      WHERE status='open' AND priority='P1'
        AND source IN ('email','sent_email','teams','teams_message','clickup_comment')
        AND updated_at < now() - interval '10 days'
        AND coalesce(module,'') <> 'VN-GOV' AND action_key NOT ILIKE '%governance%'
      RETURNING 1),
    t2 AS (
      UPDATE actions SET status='aged-stale', updated_at=now(),
        raw_json = coalesce(raw_json,'{{}}'::jsonb) || jsonb_build_object(
          'autoage_tier',2,'autoage_reason','stale_msg_p2_gt21d_noncf','autoage_run','{autoage_run}')
      WHERE status='open' AND priority='P2'
        AND source IN ('email','sent_email','teams','teams_message','clickup_comment')
        AND updated_at < now() - interval '21 days' AND is_client_facing IS NOT TRUE
        AND coalesce(module,'') <> 'VN-GOV' AND action_key NOT ILIKE '%governance%'
      RETURNING 1),
    t3 AS (
      UPDATE actions SET updated_at=now(),
        raw_json = coalesce(raw_json,'{{}}'::jsonb) || jsonb_build_object(
          'stale_verify',true,'autoage_reason','stale_msg_p2_gt21d_clientfacing','autoage_run','{autoage_run}')
      WHERE status='open' AND priority='P2'
        AND source IN ('email','sent_email','teams','teams_message','clickup_comment')
        AND updated_at < now() - interval '21 days' AND is_client_facing = TRUE
        AND coalesce(raw_json->>'stale_verify','') <> 'true'
      RETURNING 1)
    SELECT (SELECT count(*) FROM t1) p1_p2, (SELECT count(*) FROM t2) p2_done, (SELECT count(*) FROM t3) cf_flag;
    """)[0]
    # OUTPUT line: f"🧹 Auto-age (weekly): -{age['p1_p2']} P1→P2, {age['p2_done']} P2 closed, {age['cf_flag']} cf-flagged"
```

---

## STEP 3 — DRIFT AUDIT (surface only, never fix)

```python
# For each dir in /mnt/skills/user/: on-disk version vs EXPECTED_SKILL_VERSIONS (§10)
drift = [(s, on_disk, expected) for mismatches]
```
Report drift lines only. Do NOT edit files, do NOT bump the registry — that is a
human/omni-operator-learning action.

---

## STEP 4 — FLAG STRUCTURAL CANDIDATES (hand-off, no drafting)

```sql
SELECT fact_key, content FROM knowledge_facts
WHERE fact_type='operator_rule' AND status='active'
  AND (content->>'occurrences')::int >= 3 OR (content->>'severity')::int >= 8;
```
For any such rule with a clear `target_skill` → list it as a candidate and tell Nghiem:
`structural fix candidate — run omni-operator-learning to draft the patch`.
This skill never opens a SKILL.md for editing.

---

## STEP 5 — LOG + CURSOR

```python
write_action(
  skill="LEARNING", action_type="SELF_IMPROVE_RUN",
  summary=f"Self-improve ({caller}) — evals:{n_eval_issues}, promoted:{n_promoted}, merged:{n_merged}, drift:{n_drift}, struct_candidates:{n_struct}",
  metadata={"caller": caller, "eval_id": eval_id, "promoted": promoted_keys,
            "merged": merged_keys, "drift": drift_list, "struct_candidates": struct_list,
            "cursor_prev": cursor, "ran_at": now_str},
)
```
The new `SELF_IMPROVE_RUN` row's `created_at` becomes the next run's cursor (STEP 0B).

---

## OUTPUT (ultra-compact — runs after every briefing/EOD, must not bloat)

Idle:
```
Self-improve: no new signal — loop idle.
```
Active (only show non-empty lines):
```
🔄 Self-improve (<caller>): <n_eval_issues> issue(s) evaluated.
   Rules promoted/merged: <list or "none">  (live next run)
   🧹 Auto-age: <-N P1→P2, N P2 closed, N cf-flagged, or omit if gate skipped>
   ⚠️ Drift: <skill on-disk≠expected, or "none">
   🧩 Structural candidates: <skill — rule, or "none"> → run omni-operator-learning
```
Max ~5 lines. Never reprint the briefing/EOD content.

---

## GUARDRAILS

- ⛔ NEVER edit `/mnt/skills/user/` files. Behavioral tier only.
- ⛔ NEVER promote from a single occurrence (min 2). No overfitting to one run.
- ⛔ NEVER weaken governance/constitution rules — reinforce only.
- ⛔ NEVER auto-bump the §10 registry or auto-apply a structural patch — flag only.
- Token gate is mandatory: idle when no new signal; idle is free and silent.
- Never fabricate eval issues — clean output → clean PASS record.
- No new Supabase tables/columns — eval/knowledge_facts/actions only.
- Heavy work (14d synthesis, patch drafting, expiry/cleanup) belongs to
  omni-operator-learning, not here. Stay light. **Exception:** the bounded, weekly-gated,
  reversible message-action auto-age in STEP 2B (never touches live ClickUp/ADO/governance).

---

## TRIGGERS

Auto (designed): final step of `omni-eod-review` (P2), then `omni-daily-briefing` (P3).
On demand: `self improve` | `run self-improve` | `auto-train` | `close the loop`

---

## VALIDATION (P1 — before wiring the hook in P2/P3)

Run standalone once and confirm: (1) gate fires idle correctly on a no-signal re-run;
(2) one `operator_eval_reviews` row written with `created_by='self-improve'`;
(3) a seeded 2× cluster promotes to `operator_rule` and appears in the next briefing's
STEP 0A2 load; (4) drift audit reports cleanly post-P0; (5) `SELF_IMPROVE_RUN` action
logged and read back as cursor. Do NOT wire into EOD/briefing until all five pass.

---

## CHANGELOG

| Version | Change |
|---|---|
| v1.2 | **STEP 2B weekly backlog auto-age (2026-06-14).** Added a bounded, reversible data-hygiene pass for message-sourced actions that have no completion-detection path. Weekly-gated (runs ≤1×/7d via max `raw_json.autoage_run` check) so it stays light despite firing after every briefing/EOD. Tier 1: open P1 idle ≥10d → P2. Tier 2: open non-client-facing P2 idle ≥21d → `aged-stale`. Client-facing stale P2 → flagged `stale_verify`, never auto-closed. Scope locked to email/sent_email/teams/teams_message/clickup_comment; NEVER touches clickup_task/ado/calendar/governance/VN-GOV. Status/priority + raw_json audit only — never deletes; idempotent. Guardrail updated with explicit hygiene carve-out; OUTPUT gains an auto-age line. Follows the one-time 2026-06-14 manual P1 grooming (136→73) to keep the backlog self-cleaning. No new tables/columns. |
| v1.1 | **Gate token fix (P4).** STEP 0C `new_output` now detects the real run log token — `actions WHERE skill IN ('EOD','BRIEFING') AND action_type='REVIEWED'` — instead of the non-existent `EOD_RUN`/`BRIEFING_RUN`. No behavior change on the hook path (caller passes new_output=True), but standalone on-demand `self improve` now gates correctly against the last briefing/EOD run. Registered in omni-config §10 v1.8. |
| v1.0 | Initial. Post-run behavioral auto-train hook: token gate (cursor from actions.SELF_IMPROVE_RUN), 5-check light inline eval → operator_eval_reviews, delta-window ≥2× promotion to operator_rule (auto-applied at STEP 0A2), drift audit (surface only), structural-candidate flagging (hand-off to omni-operator-learning). Hard autonomy boundary: never edits SKILL.md, never weakens governance, never promotes single-occurrence. Registered in omni-config §10 v1.6. |
