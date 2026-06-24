---
name: omni-daily-briefing
version: "7.3"
description: "OMNI Chief-of-Staff Daily Briefing. v7.2: Feature Board — renders feature_rollup from context pack as per-OPCO feature status board; surfaces status_conflicts for review and candidate features to confirm. Requires omni-utils v11.1 + omni-data-sync v12.2. v7.0: Supabase-only — Mem0 fully retired. Adds STEP 0 eval lessons from operator_eval_reviews. Cleans legacy Mem0 fallback paths. Retains STEP 0B safety check (direct Supabase P1 query), auto-LIGHTWEIGHT sync on stale, write_action() log. Output: simplified P0/P1/P2/Watchlist structure, max 5 reply items. Triggers: 'run briefing', 'morning briefing', 'evening briefing', 'what do I need to know today', 'AI daily briefing'."
---

# OMNI Daily Briefing — v7.3

## ⚠️ READ FIRST — SHARED CONFIG + UTILS

**Before any step, read:**
1. `/mnt/skills/user/omni-config/SKILL.md` → loads constants (CONFIG_VERSION = "1.3")
2. `/mnt/skills/user/omni-utils/SKILL.md` → loads utilities (UTILITY_VERSION = "11.0")

---

## Operating Mode — Supabase-only

- Supabase is the **sole** source of truth.
- Do **NOT** read Mem0 — not as primary, not as fallback.
- Do **NOT** write Mem0 under any circumstance.
- Mark Mem0 as: `SKIPPED — Mem0 retired`
- If Supabase is unavailable → `cache_check()` returns `degraded=True` → warn user, output marked degraded. No Mem0 fallback path exists.

---

## STEP 0 — EVAL LESSONS + CACHE LOAD + SAFETY CHECK

### STEP 0A — Load Recent Eval Lessons (always first)

Before any output is generated, query the last 3 records from `operator_eval_reviews`, ordered by `created_at DESC`.

```sql
-- v7.1/v9.1 fix: `prevention_rules` is not a column — prevention rules live inside
-- the `recommended_fixes` / `findings` jsonb payloads.
SELECT run_date, findings, missed_actions, decision_review, reply_required_review,
       risk_review, recommended_fixes
FROM operator_eval_reviews
ORDER BY created_at DESC
LIMIT 3;
```

Extract active prevention rules (from `recommended_fixes` + `findings` jsonb) covering:
- Repeated issues
- Severity >= 7 issues
- Missed client-facing actions
- Missed reply-needed items
- Wrong confirmed/pending decision classification
- Missed governance-sensitive risks

Apply these prevention rules during this run. They must influence:
- P0/P1/P2/Watchlist ranking
- Reply-needed detection
- Decision status classification
- Governance-sensitive item detection
- Risk detection
- Meeting preparation
- Suggested drafts

Do NOT write to Mem0.

**If `operator_eval_reviews` table does not exist:**
→ Continue and state: `operator_eval_reviews table missing — eval lessons skipped.`

**If table exists but no records:**
→ Continue and state: `No prior eval lessons found — baseline rules applied.`

Show only this summary line in the output header:
`Eval lessons loaded: <N> recent reviews; active prevention rules applied: <N>.`

### STEP 0A2 — Load Promoted Operator Rules + Version Handshake (v7.1)

```sql
SELECT fact_key, content FROM knowledge_facts
WHERE fact_type = 'operator_rule' AND status = 'active'
ORDER BY (content->>'severity')::int DESC NULLS LAST
LIMIT 25;   -- LEARNING_MAX_ACTIVE_RULES from omni-config §10B
```

Apply each rule's `content.instruction` alongside STEP 0A prevention rules — same scope
(ranking, reply detection, decision classification, governance items, risks, drafts).
If table/rows missing → continue silently.

**Version handshake:** compare this skill's on-disk version against
`EXPECTED_SKILL_VERSIONS` in omni-config §10. On mismatch print:
`⚠️ VERSION DRIFT: omni-daily-briefing on-disk v<X> ≠ registry v<Y>` and continue.

Append to header line: `Operator rules applied: <N>.`

---

### STEP 0B — Supabase Context Pack Load

⛔ **BLOCKED Mem0 structured cache tags — DO NOT READ under any circumstance:**
`[SYNC-META]`, `[EMAILS]`, `[TEAMS+CLICKUP]`, `[URGENT+CALENDAR]`, `[CLICKUP-CACHE]`, `[CLICKUP-COMMENTS]`

Call `cache_check()` → reads `sync_runs` in Supabase.

```python
ctx = get_context_pack("briefing", stale_threshold_h=CACHE_BRIEFING_H)
# Expected: source="supabase", degraded=false

if ctx["needs_sync"]:
    print(f"⚡ Cache stale/missing ({ctx['cache_age_h']}h old) — auto-running LIGHTWEIGHT sync...")
    run_omni_data_sync(mode="LIGHTWEIGHT")
    ctx = get_context_pack("briefing", stale_threshold_h=CACHE_BRIEFING_H)

ctx_source    = ctx.get("source", "unknown")    # expected: "supabase"
ctx_degraded  = ctx.get("degraded", True)       # expected: False
ctx_sync_id   = ctx.get("sync_id", "unknown")
ctx_loaded_at = ctx.get("loaded_at", "unknown")
ctx_age_h     = ctx.get("cache_age_h", 99)

if ctx_source == "supabase" and not ctx_degraded:
    cache_mode = "CACHE" if not ctx["needs_sync"] else "WARN"
else:
    cache_mode = "DEGRADED"
    # Surface warning to user — no Mem0 fallback
    print("⚠️ Supabase unavailable or degraded — output marked DEGRADED. Recommend running omni-data-sync.")
```

**Map context pack fields:**
```python
top_actions            = ctx["data"].get("top_actions", [])
open_risks             = ctx["data"].get("open_risks", ctx["data"].get("top_risks", []))
decisions              = ctx["data"].get("decisions", [])
client_facing_open     = ctx["data"].get("client_facing_open_actions",
                         ctx["data"].get("waiting_on_client", []))
waiting_on_team        = ctx["data"].get("waiting_on_team", [])
clickup_replies_needed = ctx["data"].get("clickup_replies_needed", [])
meetings_to_prepare    = ctx["data"].get("meetings_to_prepare", [])
suggested_drafts       = ctx["data"].get("suggested_drafts", [])
briefing_notes         = ctx["data"].get("briefing_notes", [])
```

---

### STEP 0C — Open Actions Safety Check (always run, never skip)

**Purpose:** Catch open P1 actions and stakeholder-linked items not yet surfaced in the context pack.

```python
PRIORITY_STAKEHOLDERS = [
    "Zach", "Andrea", "Kezia", "Huy Phan", "Kay Sheng",
    "Michelle", "Kinneth", "Angelia", "Roy",
]

# Query open P1 actions not already in top_actions
open_p1_actions = supabase_sql("""
    SELECT action_key, title, owner, due_date::text, source, module, market,
           priority, status, draft_reply, is_client_facing
    FROM actions
    WHERE status IN ('open','in_progress','blocked')
      AND priority = 'P1'
      AND updated_at >= now() - INTERVAL '48 hours'
    ORDER BY due_date ASC NULLS LAST
    LIMIT 10;
""") or []

# Query stakeholder-linked open actions
stakeholder_filter = " OR ".join([f"title ILIKE '%{s}%'" for s in PRIORITY_STAKEHOLDERS])
stakeholder_actions = supabase_sql(f"""
    SELECT action_key, title, owner, due_date::text, source, module, market,
           priority, status, draft_reply, is_client_facing
    FROM actions
    WHERE status NOT IN ('done','cancelled')
      AND ({stakeholder_filter})
    ORDER BY priority ASC, due_date ASC NULLS LAST
    LIMIT 10;
""") or []

# Deduplicate against context pack
existing_keys = {a.get("action_key") for a in top_actions}
safety_surfaced = [
    a for a in open_p1_actions + stakeholder_actions
    if a.get("action_key") not in existing_keys
]

if safety_surfaced:
    print(f"[STEP 0C] safety_check_surfaced: {len(safety_surfaced)} additional items not in primary context pack")
else:
    print("[STEP 0C] safety_check_clean: all open P1 and stakeholder actions already in context pack")
```

Surface `safety_surfaced` items in a `⚠️ Possible Missed Actions` sub-section under P1/P2 as appropriate. Mark with stale-context qualifier if source date > 7 days old:
> `"As of [date], this was pending — verify current status"`

---

## Required Supabase Reads

If context pack is missing, stale, or incomplete — inspect these tables directly and compile a temporary context pack. Warn clearly in output header.

| Table | What to read |
|---|---|
| `sync_runs` | Latest sync timestamp, status, failed sources |
| `context_packs` | Latest `briefing` and `eod` packs |
| `source_items` | Today / last 24h — types: email, sent_email, teams_message, clickup_task, clickup_comment, calendar_event |
| `actions` | Open/in_progress/blocked — due today, overdue, client-facing, governance-sensitive |
| `risks` | Open/monitoring/blocked risks |
| `decisions` | Last 14 days — classify cautiously |
| `knowledge_facts` | Latest intel_daily, intel_weekly, active intel_pattern |
| `operator_eval_reviews` | Last 3 records (STEP 0A) |

---

## Priority Ranking Rules

Rank all actionable items:

### P0 — Handle First
- Client-facing blockers due today
- Senior stakeholder direct questions due today
- Production/deployment risks
- Critical meetings today
- Immediate scope/SOW/capacity controls
- Overdue P1s where a stakeholder is waiting
- Governance-sensitive items requiring action before external communication

**Each P0 item must include:** owner · next step · deadline · source/evidence

### P1 — Important Today
- Replies needed from Nghiem
- Client-facing follow-up
- Delivery dependencies
- Tomorrow's senior meeting preparation
- Unresolved P1 risks
- Blockers that may affect delivery
- Governance-sensitive items not yet P0

### P2 — Follow Up
- Internal follow-up
- Non-blocking clarification
- Normal status updates
- Useful coordination
- Items without immediate external impact

### Watchlist
- Future/informational items
- Non-urgent risks
- Monitoring items
- Weak signals without enough proof

---

## Reply-Needed Detection

Detect direct question/reply-needed items from priority stakeholders:

**Priority stakeholders:** Andrea · Kay Sheng · Kezia · Angelia · Zach · Roy · Michelle · Huy Phan · Ha Hoang · Kinneth · Tan Vu · Hung Nguyen · Hoang Ngo

**Detection phrases:** `can you` · `could you` · `please confirm` · `let me know` · `what is` · `when will` · `do you know` · `?` directed at Nghiem/team · `anh check` · `anh confirm` · `cho anh biết` · `khi nào`

**Escalation rules:**
- Tier 1 senior/client direct questions → P1
- Tier 1 due today → P0
- Tier 2/internal → P2
- Tier 2 blocking → P1
- Past-due replies escalate one level

---

## ClickUp Comment Detection

Never discard comments signalling: `REQUIREMENT_CHANGE` · `CLARIFICATION` · `SCOPE_RISK` · `DECISION` · `CLIENT_CONCERN` · `STATUS_MISMATCH` · `BLOCKER`

---

## Reply Queue Boundary Rule

In `Replies Needed`, show **only**:
- P0/P1 replies
- Replies due today
- Senior stakeholder replies
- Governance-sensitive replies
- Blocker/risk replies

**Maximum: 5 reply items.**

For all others, show only:
`Other pending ClickUp replies: <count>. Run "Check OMNI comment reply queue" for details.`

**Every reply-needed item must include:** source · from · topic · priority · suggested reply · human review: yes/no

**Human review = yes if the reply may:**
- Commit scope/timeline/cost/capacity
- Involve SOW/FTE/budget/contract/governance
- Involve Andrea/Kay Sheng/Angelia/Kezia/Zach/YiLun/Peter
- Require uncertain technical answer
- Have unclear owner
- Require a decision before replying
- Have low confidence

**Email sign-off:** `Regards,` · ClickUp comments: no sign-off

---

## Governance-Sensitive Items

Flag anything involving: scope · SOW · capacity · FTE · budget · resource allocation · contract · handover · ownership · senior stakeholder communication · Andrea · Kay Sheng · Zach · YiLun · Peter

**For each item include:** status · client-facing: yes/no · SOW impact: yes/no/possible · communication protocol · next step

**Default rule:** Do not externally commit to scope/capacity/timeline/cost/delivery date before internal alignment.
**VN-GOV/Andrea:** Route via YiLun first. CC Peter if needed.

---

## Decision Classification

Decision statuses (mandatory on every decision):

| Status | When to use |
|---|---|
| `confirmed` | Explicit evidence of acceptance — ownership, scope, and next step accepted |
| `proposed` | One party suggested; no internal acceptance yet |
| `pending` | Under active discussion, not yet agreed |
| `pending_alignment` | Internally discussed but not yet aligned |
| `unclear` | Signal detected but ambiguous |
| `rejected` | Explicitly declined or overruled |

- **Only `confirmed` decisions appear under Confirmed Decisions.**
- Client requests, scheduled meetings, and proposals are NEVER `confirmed`.
- When in doubt → `proposed`.

---

## Feature Board (v7.2)

Read `pack.data.feature_rollup` (from `feature_status` via context pack). If the key is
missing (pre-v12.2 pack) → render "Feature board: not available — run sync data first."

Rendering rules:
- Group by OPCO; one line per feature:
  `<label> — <STATUS> (<status_signal> via <status_source>, <date>) — <status_summary ≤15w>`
- Sort: incident → blocked → at_risk → deployed → decided → in_progress/other.
- Show ONLY: features with status ≠ 'unknown', OR conflict_count > 0, OR
  registry_state = 'candidate'. Cap 12 lines; collapse rest to "+N more stable features."
- `unknown` status with signals = "tracking, no status-bearing signal yet" — do NOT invent a status.

Conflicts (review required):
- Any feature with conflict_count > 0 → list under "⚠️ Status Conflicts" with the
  conflicting signal summary + current status. These are lower-confidence signals that
  did NOT auto-apply — Nghiem decides: accept (state it in chat) or ignore.

Candidates (registry grows daily):
- registry_state='candidate' rows → list under "🆕 Feature Candidates" with alias phrase
  + signal count. Ask: confirm / merge into existing / reject. On Nghiem's answer,
  update feature_status.registry_state accordingly (confirmed|rejected) or merge aliases.

Cross-link rule: if a P0/P1 action has feature_key, append `[<feature label>]` to its
line — keeps actions and feature board visibly connected.

---

## Meetings to Prepare

Include meetings from today and next 48 hours. Prioritize: Andrea · Kay Sheng · Zach · Kezia · Angelia · client-facing · governance/capacity/scope · deployment/release/demo · FieldAssist · REP India · TPM · MM HAP demos

Each item: time (GMT+7) · title · module/OPCO · prep needed · risk/decision/stakeholder angle

---

## Pattern Promotion Rule

Do not promote a new pattern unless it appears across **3+ distinct days** or severity >= 9 across 3+ days.
If insufficient evidence: `No new pattern promoted — insufficient historical proof.`

---

## Suggested Drafts

Only when source-backed, enough context exists, and no unsafe commitment is made.

Style: concise · neutral · non-committal on scope/timeline/capacity · business-first · direct
Email sign-off: `Regards,` · ClickUp comments: no sign-off

---

## Required Output Format

```markdown
# OMNI DAILY BRIEFING — <YYYY-MM-DD> <Morning/Evening> (GMT+7)

Context:
- Supabase latest sync: <timestamp / status>
- Context pack freshness: <fresh / stale / missing / compiled temporary>
- Sources failed / missing: <none / list>
- Eval lessons: <N reviews loaded; N prevention rules applied / table missing / no records>
- Mem0: SKIPPED — Mem0 retired

## P0 Handle First

## P1 Important Today

## P2 Follow Up

## Watchlist

## Feature Board (by OPCO)

⚠️ Status Conflicts: <none / list>
🆕 Feature Candidates: <none / list — confirm/merge/reject>

## Replies Needed

Other pending ClickUp replies: <count>. Run "Check OMNI comment reply queue" for details.

## Meetings to Prepare

## Confirmed Decisions

## Pending Alignment / Decision Needed

## Governance-Sensitive Items

## Open Risks

## Context From EOD / Knowledge Facts

## Suggested Drafts

## Top 5 Focus for Nghiem

## Write-Back
```

---

## Top 5 Focus for Nghiem

Exactly **5** prioritized actions. Each must include:
- Priority number
- Action
- Owner
- Deadline (if known)
- Reason / impact
- Next step

---

## STEP 7 — WRITE ACTION LOG (always, silent)

Call `write_action()` from omni-utils. Do NOT skip.

```python
briefing_type = "Morning" if current_hour < 12 else "Evening"

write_action(
    skill       = "BRIEFING",
    action_type = "REVIEWED",
    summary     = f"{briefing_type} briefing delivered",
    metadata    = {
        "p0_count":             len(p0_items),
        "p1_count":             len(p1_items),
        "p2_count":             len(p2_items),
        "mode":                 cache_mode,
        "type":                 briefing_type,
        "reply_queue_count":    len([r for r in clickup_replies_needed if r.get("response_needed")]),
        "safety_surfaced":      len(safety_surfaced),
        "eval_lessons_applied": eval_prevention_rules_count,
        "context_source":       ctx_source,
        "context_sync_id":      ctx_sync_id,
        "context_degraded":     str(ctx_degraded),
        "context_age_h":        str(round(ctx_age_h, 1)),
    }
)
```

---

## Write-Back Rule

After producing the briefing, write back only if write access is available and useful.

**Allowed write-backs:**
- `actions` — missing reply-required or follow-up items
- `knowledge_facts` — durable insights only (fact_type: intel_daily, intel_decision)
- `context_packs` — only if refreshed briefing pack is required

**Never write to Mem0.**

If write-back fails or is unavailable:
`Supabase write-back failed or unavailable — no Mem0 fallback used.`

---

## STEP 8 — SELF-IMPROVE HOOK (final, auto — never skip)

This is what makes the operator self-training with **no manual trigger**. After the briefing
output is delivered and STEP 7 (action log) + write-backs have run, invoke the behavioral
auto-train loop.

Read `/mnt/skills/user/omni-self-improve/SKILL.md` and execute it with:
```python
caller     = "BRIEFING"
new_output = True          # this run just produced output → self-improve gate passes by construction
output_ref = {             # what self-improve inline-evaluates (STEP 1)
    "top_actions": p0_items + p1_items + p2_items,
    "replies":     clickup_replies_needed,
    "safety":      safety_surfaced,        # from STEP 0C
    "context":     {"source": ctx_source, "degraded": ctx_degraded, "age_h": ctx_age_h},
}
```

self-improve will: light 5-check inline-eval → write one `operator_eval_reviews` row →
promote any ≥2× cluster to `operator_rule` (auto-applied at the **next** briefing/EOD
STEP 0A2, no human step) → drift audit (surface only) → flag structural candidates for
`omni-operator-learning`. Append its ~5-line compact output **below** the briefing.

**Hook guardrails (fail-open, non-negotiable):**
- Behavioral tier only — self-improve NEVER edits SKILL.md and NEVER weakens governance
  (YiLun→Andrea routing, capacity protocol). It may reinforce them, never override.
- **Fail-open:** if self-improve errors or its tables are missing, print one line
  `self-improve hook skipped: <reason>` and finish cleanly. The hook must NEVER block,
  delay, or corrupt the briefing itself — the morning briefing is the most action-critical
  output and takes priority over the learning loop.
- No double-run: if a `SELF_IMPROVE_RUN` action for caller="BRIEFING" is already logged at
  or after this run's start timestamp, skip silently.

---

## Non-Negotiables

- Supabase first, always.
- Mem0 skipped and retired — zero reads, zero writes, zero fallbacks.
- Load eval lessons (STEP 0A) before any output.
- Run STEP 0C safety check in every mode.
- Auto-LIGHTWEIGHT sync if context pack is stale.
- Do not invent facts.
- Do not silently mark decisions as confirmed.
- Do not duplicate the full ClickUp Reply Queue — max 5 items.
- Do not resolve risks without Supabase evidence.
- Do not make external scope/timeline/capacity commitments without internal alignment.
- Top 5 Focus must contain exactly 5 actions.
- Every P0 item must include owner, next step, deadline, and source evidence.
- Feature Board renders from feature_rollup only — never invent feature statuses; 'unknown' stays unknown.
- Status Conflicts and Candidates are decisions for Nghiem — never auto-accept a conflict or auto-confirm a candidate from the briefing.
- Self-improve hook (STEP 8) runs as the final step, fail-open — behavioral tier only, never edits skills, never blocks the briefing on failure.

---

## CHANGELOG

| Version | Change |
|---|---|
| v7.3 | **Self-improve hook wired (P3).** New final STEP 8 invokes `omni-self-improve` (caller="BRIEFING", new_output=True) after STEP 7 + write-backs — closes the behavioral auto-train loop with no manual trigger: inline-eval the briefing → promote ≥2× clusters to `operator_rule` (live at next STEP 0A2). Fail-open (hook errors never block the briefing); behavioral tier only (never edits SKILL.md, never weakens governance); no double-run guard. Registered in omni-config §10 v1.7. |
| v7.2 | **Feature Board** (2026-06-11). New output section rendering `feature_rollup` per-OPCO (sorted incident→blocked→at_risk→deployed; cap 12 lines). Surfaces ⚠️ Status Conflicts (lower-confidence signals awaiting Nghiem decision) and 🆕 Feature Candidates (auto-discovered; confirm/merge/reject updates registry_state). P0/P1 actions cross-linked via feature_key label. Requires context pack from omni-data-sync v12.2. |
| v7.0 | **Merged: uploaded new logic + production guardrails.** Added STEP 0A eval lessons from `operator_eval_reviews` (last 3 records, extract prevention rules, apply to all ranking/detection). STEP 0B/0C renumbered (was 0A/0B). Removed all Mem0 fallback paths — `ctx_source="mem0_legacy"` path deleted; degraded=true now surfaces warning only. Removed legacy Mem0 write instructions from STEP 7 (no `[ACTION]`, `[DECISION]`, `[RISK]` Mem0 writes). Simplified output format to 14 clean sections matching uploaded spec. Reply queue capped at max 5 (was 8). `write_action()` extended with `safety_surfaced` and `eval_lessons_applied` fields. All blocked Mem0 tag list retained as explicit guardrail. |
| v6.0 | Supabase context source. Blocked Mem0 structured cache tags. Context pack field mapping. |
| v5.0 | Phase 3A Supabase context. STEP 0B safety check introduced. |
| v4.x | Atomic memory safety scan, direct-question detection, stale-context qualifier. |
| v3.0 | ClickUp Comment Signal integration. |
| v2.x | omni-config + omni-utils. Auto LIGHTWEIGHT sync. |
| v1.0 | Initial version. |
