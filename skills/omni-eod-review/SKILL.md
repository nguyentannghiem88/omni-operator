---
name: omni-eod-review
version: "9.4"
description: "OMNI End-of-Day Project Intelligence Review. v9.4: pattern-mining decisions query filters superseded_by IS NULL so omni-data-sync v12.5 merged duplicate decisions no longer re-enter EOD frequency maps (pairs with omni-utils v11.2). v9.2: Feature Rollup EOD duties — feature status changes today, supersede audit, status-conflict review, and candidate confirm/merge/reject (the designated daily registry-growth checkpoint). Requires omni-utils v11.1 + omni-data-sync v12.2. v9.0: Supabase-only — Mem0 fully retired. Adds STEP 0 eval lessons from operator_eval_reviews. Removes all Mem0 fallback paths and allowed-write references. Retains write_action() log, upsert_context_pack(eod), technical assumptions and stakeholder concerns sections. Top 5 Focus enforced at exactly 5. Triggers: 'end of day review', 'EOD review', 'daily analysis', 'what happened today', 'analyze today', 'daily debrief', 'wrap up today'. Run once per day. Weekly synthesis every Monday."
---

# OMNI EOD Review — v9.3

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
- Do not invent facts. If evidence is missing, mark items as `unclear`, `pending`, or `needs_review`.
- Use exact dates/times in GMT+7.

---

## Memory Architecture

| Layer | Table / fact_type | Retention | Purpose |
|---|---|---|---|
| Daily snapshot | `knowledge_facts` · `intel_daily` | 60 days rolling | Full structured JSON per day |
| Weekly synthesis | `knowledge_facts` · `intel_weekly` | 90 days rolling | Synthesized from 7 daily entries |
| Persistent patterns | `knowledge_facts` · `intel_pattern` | Indefinite | Topics repeated 3+ times |
| Key decisions | `decisions` table | Indefinite | Important decisions, never expire |
| Open risks | `risks` table | Until resolved | Active risks, updated daily |
| EOD context pack | `context_packs` · `pack_type=eod` | Supabase cache | Feeds next morning's briefing |

---

## STEP 0 — PRE-FLIGHT

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

Apply prevention rules during this run. They must influence:
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

---

### STEP 0A2 — Load Promoted Operator Rules + Version Handshake (v9.1)

```sql
SELECT fact_key, content FROM knowledge_facts
WHERE fact_type = 'operator_rule' AND status = 'active'
ORDER BY (content->>'severity')::int DESC NULLS LAST
LIMIT 25;
```

Apply each rule's `content.instruction` alongside STEP 0A prevention rules.
Version handshake: compare on-disk version vs `EXPECTED_SKILL_VERSIONS` (omni-config §10);
warn on mismatch, continue. If table/rows missing → continue silently.

### STEP 0B — Get Current Time

Call `user_time_v0` → extract date (YYYY-MM-DD), weekday, week number (ISO).

---

### STEP 0C — Load Past Intelligence (for pattern detection)

```sql
SELECT * FROM knowledge_facts
WHERE fact_type = 'intel_daily'
ORDER BY updated_at DESC LIMIT 7;

SELECT * FROM knowledge_facts
WHERE fact_type = 'intel_pattern' AND status = 'active';

SELECT * FROM risks WHERE status IN ('open','monitoring');

SELECT * FROM decisions
WHERE run_date >= CURRENT_DATE - INTERVAL '14 days'
  AND superseded_by IS NULL;
```

Extract from daily entries:
- Topics/blockers mentioned in last 7 days → build frequency map
- Any item appearing 3+ times → flag as candidate for PATTERN promotion

---

## STEP 1 — LOAD CONTEXT VIA SUPABASE

⛔ **DO NOT read Mem0 — not as primary, not as fallback, under any circumstance.**
⛔ **BLOCKED Mem0 structured cache tags:** `[SYNC-META]`, `[EMAILS]`, `[TEAMS+CLICKUP]`, `[URGENT+CALENDAR]`, `[CLICKUP-CACHE]`, `[CLICKUP-COMMENTS]`

```python
ctx = get_context_pack("eod_review", stale_threshold_h=CACHE_EOD_H)
# Expected: source="supabase", degraded=false

if ctx["source"] == "supabase" and not ctx["degraded"]:
    print("[eod_context_source_supabase] ✅ Supabase context loaded — degraded=false")
else:
    # Supabase unavailable — warn user, no Mem0 fallback
    print("⚠️ Supabase unavailable or degraded — EOD running in DEGRADED mode. Recommend running omni-data-sync.")

if ctx["needs_sync"]:
    print(f"⚡ Cache stale/missing ({ctx['cache_age_h']}h old) — auto-running FULL sync...")
    run_omni_data_sync(mode="FULL")
    ctx = get_context_pack("eod_review", stale_threshold_h=CACHE_EOD_H)
```

### 1A — Map Context Pack Fields

```python
top_actions            = ctx["data"].get("top_actions", [])
decisions              = ctx["data"].get("decisions", [])
open_risks             = ctx["data"].get("open_risks", [])
meetings_to_prepare    = ctx["data"].get("meetings_to_prepare", [])
client_facing_open     = ctx["data"].get("client_facing_open_actions",
                         ctx["data"].get("waiting_on_client", []))
waiting_on_team        = ctx["data"].get("waiting_on_team", [])
clickup_replies_needed = ctx["data"].get("clickup_replies_needed", [])
suggested_drafts       = ctx["data"].get("suggested_drafts", [])
briefing_notes         = ctx["data"].get("briefing_notes", [])
intel_daily            = ctx["data"].get("intel_daily", [])
intel_pattern          = ctx["data"].get("intel_pattern", [])
feature_rollup         = ctx["data"].get("feature_rollup", [])   # v9.2
```

### 1B — Derive Reply Queue

```python
reply_queue_pending      = [r for r in clickup_replies_needed if r.get("response_needed")]
reply_queue_human_review = [r for r in clickup_replies_needed if r.get("human_review")]
reply_queue_overdue      = [r for r in clickup_replies_needed if r.get("urgency") == "today" and r.get("response_needed")]
```

### 1C — Derive Comment Signals

```python
merged_comment_signals = [
    item for item in (briefing_notes + top_actions)
    if item.get("source") in ("clickup_comment", "comment_signal")
]

cs_blockers        = [s for s in merged_comment_signals if s.get("signal_type") == "BLOCKER"]
cs_decisions       = [s for s in merged_comment_signals if s.get("signal_type") == "DECISION"]
cs_req_changes     = [s for s in merged_comment_signals if s.get("signal_type") == "REQUIREMENT_CHANGE"]
cs_scope_risks     = [s for s in merged_comment_signals if s.get("signal_type") == "SCOPE_RISK"]
cs_mismatches      = [s for s in merged_comment_signals if s.get("metadata_mismatch") == True]
cs_client_concerns = [s for s in merged_comment_signals if s.get("signal_type") == "CLIENT_CONCERN"]
```

---

### 1D — Derive Feature Rollup Views (v9.2)

```python
feat_changed_today = [f for f in feature_rollup
                      if f.get("status_updated_at","")[:10] == today]
feat_conflicts     = [f for f in feature_rollup if f.get("conflict_count",0) > 0]
feat_candidates    = [f for f in feature_rollup if f.get("registry_state") == "candidate"]

# Supersede audit (today's auto-superseded actions — verify rollup behaved):
superseded_today = supabase_sql(f"""
    SELECT action_key, title, feature_key,
           raw_json->>'superseded_reason' AS reason
    FROM actions
    WHERE raw_json->>'superseded_by' IS NOT NULL
      AND (raw_json->>'superseded_at')::date = '{today}'::date;
""")
```

If `feature_rollup` key missing (pre-v12.2 pack): render "Feature rollup: not available — run sync data first." and skip 1D-dependent sections.

---

## STEP 2 — EXTRACT + CLASSIFY INTELLIGENCE SIGNALS

Map `top_actions` → URGENT/BLOCKER signals.
Map `waiting_on_client` → BLOCKER signals (blocked_by: client).
Map `waiting_on_team` → BLOCKER signals (blocked_by: internal).
Override INFO signals with BLOCKER if a comment signal (`cs_blockers`) targets the same task.

**Decision classification — mandatory `decision_status` on every decision:**

| decision_status | When to use |
|---|---|
| `confirmed` | Ownership, scope, and next step explicitly accepted |
| `proposed` | One party suggested; no acceptance yet |
| `pending_alignment` | Internally discussed but not yet aligned |
| `unclear` | Ambiguous — cannot determine agreed or proposed |
| `rejected` | Explicitly declined or overruled |

⚠️ **A client request or proposal is NEVER `confirmed`. When in doubt → `proposed`.**

Do NOT classify these as confirmed: client requests · scheduled meetings · proposals · options under discussion · suggested approaches · assumptions · single stakeholder opinion without approval.

### 2A — Write Live Decision Register

```python
for d in all_decisions:
    write_action(
        skill       = "DECISION",
        action_type = "RECORDED",
        summary     = d.get("description","")[:80],
        metadata    = {
            "decision_status":      d["decision_status"],
            "module":               d.get("module","OMNI"),
            "opco":                 d.get("opco","ALL"),
            "decided_by":           d.get("decided_by") or d.get("proposed_by","unknown"),
            "governance_sensitive": d.get("governance_sensitive", False),
            "comm_protocol":        "YiLun only (Peter CC)" if d.get("governance_sensitive") and d.get("sow_scope_impact") else "internal",
            "sow_scope_impact":     d.get("sow_scope_impact", False),
            "source":               d.get("source","EOD"),
        }
    )
```

---

## STEP 3 — SYNTHESIZE OUTPUT

### Required Output Structure

```markdown
# OMNI EOD REVIEW — <YYYY-MM-DD> (GMT+7)

Context: Supabase
Supabase latest sync: <status / timestamp>
Context pack freshness: <fresh / stale / missing / compiled temporary>
Sources failed: <none / list>
Mem0: SKIPPED — Mem0 retired
Eval lessons loaded: <N> recent reviews; active prevention rules applied: <N>.

## Executive Summary
<3–5 bullet points: what mattered today, critical blockers, major progress, unresolved governance>

## P0 — Handle First
<client-facing blockers due today · senior stakeholder questions due today · production/deployment risks · scope/SOW/capacity controls>
Each item: owner · next step · deadline · source evidence

## P1 — Important Follow-Up
<replies needed · client follow-up · delivery dependencies · meeting prep · unresolved risks>
Each item: owner · next step · deadline

## P2 — Normal Follow-Up
<internal follow-up · non-blocking coordination · items not due today but operationally relevant>

## Watchlist
<future/informational/non-urgent · monitoring-only · upcoming topics without action today>

## Replies Needed
<Maximum 5 items: P0/P1, due today, senior stakeholder, governance-sensitive, blocker/risk only>
Each item: source · from · topic · priority · suggested reply · human review: yes/no
Other pending ClickUp replies: <count>. Run "Check OMNI comment reply queue" for details.

## Completed / Moved Today
<max 5 bullets — sourced from top_actions with status completed/done>

## Still Open
<sourced from top_actions + waiting_on_team>

## Waiting on Client
| Item | Module | OPCO | Waiting For | Days Open |

## Waiting on Team
| Item | Module | OPCO | Owner | Next Step |

## Meetings / Prep Carry-Over
<today's meeting outcomes if evidence exists · next 48h meetings to prepare>

## Confirmed Decisions
<Only decision_status=confirmed. Include: decision · owner/source · date · impact>
If none: "None confirmed today."

## Pending Alignment / Decision Needed
<proposed / pending / pending_alignment / unclear items>
Each: owner to decide · next step

## Governance-Sensitive Items
<status · client-facing: yes/no · SOW impact: yes/no/possible · comm protocol · next step>

## Open Risks
| Module/OPCO | Risk | Severity | Owner | Mitigation | Status |

## Requirement / Scope Changes Detected
<summarize requirement-change signals from emails, Teams, ClickUp, ADO>
<Recommend Requirement Analyzer if details need extraction>

## Technical Assumptions (Unvalidated)
<[module] assumption — owner — validate via: suggestion>

## Stakeholder Concerns
<[stakeholder] concern — status: open/acknowledged/resolved>

## ClickUp Comment Signals — EOD Check
<only if merged_comment_signals non-empty>
1. Comments needing response today: <N>
2. New risks/blockers from comments: <N>
3. Scope/requirement changes: <N>
4. Decisions confirmed in comments: <N>
5. Client/stakeholder follow-ups: <N>
6. Status mismatches (task ≠ comment): <N>

## Feature Status Changes Today
<from feat_changed_today: label — old→new status, deciding signal source + actor. If none: "No feature status changes today.">

## Auto-Superseded Actions (audit)
<from superseded_today: action title — superseded_by feature + reason. Flag any that look WRONG (rollup superseded something still needed) → reopen: UPDATE actions SET status='open', raw_json=raw_json||'{"reopened_by":"eod_audit"}' WHERE action_key=...; and silently capture operator_feedback per correction rule. If none: "No auto-supersedes today.">

## ⚠️ Feature Status Conflicts — Review Required
<from feat_conflicts: feature label, current status, conflicting signal summary. Ask Nghiem: accept conflict signal as new status, or dismiss? On answer: accept → apply status + clear conflicts[]; dismiss → clear conflicts[] only.>

## 🆕 Feature Candidates — Confirm / Merge / Reject
<from feat_candidates: candidate label, alias phrase(s), signal_count, sample signal titles.
For each, ask Nghiem: (1) confirm → registry_state='confirmed'; (2) merge into <existing feature_key> → move aliases to target row via array_cat, re-tag source_items, set candidate registry_state='rejected'; (3) reject → registry_state='rejected'. This is the daily registry-growth checkpoint — candidates never auto-supersede until confirmed.>

## Patterns Flagged
<only if 3+ occurrences across 3+ distinct calendar days>
If insufficient: "No new pattern promoted — insufficient historical proof."

## Context From Knowledge Facts
<relevant intel_daily, intel_weekly, intel_pattern>

## Suggested Drafts
<source-backed only · mark human review required where applicable>

## Top 5 Focus for Nghiem Tomorrow
<Exactly 5 items: priority · action · owner · next step · deadline>

## Write-Back
<state what was written back or why not>
```

---

## Reply Queue Boundary Rule

In `Replies Needed`, show **only**:
- P0/P1 replies
- Replies due today
- Senior stakeholder replies
- Governance-sensitive replies
- Blocker/risk replies

**Maximum: 5 reply items.**

For all others:
`Other pending ClickUp replies: <count>. Run "Check OMNI comment reply queue" for details.`

**Every reply-needed item must include:** source · from · topic · priority · suggested reply · human review: yes/no

**Human review = yes if:** commits scope/timeline/cost/capacity · involves SOW/FTE/budget/contract/governance · involves Andrea/Kay Sheng/Angelia/Kezia/Zach/YiLun/Peter · uncertain technical answer · unclear owner · requires decision before replying · low confidence

**Email sign-off:** `Regards,` · ClickUp comments: no sign-off

---

## Governance-Sensitive Item Detection

Flag anything involving: scope · SOW · capacity · FTE · budget · resource allocation · contract · handover · ownership · senior stakeholder communications · timeline commitments · production/release commitments

Priority governance stakeholders: Andrea · Kay Sheng · Zach · YiLun · Peter · Kezia · Angelia

For each item: status · client-facing: yes/no · SOW impact: yes/no/possible · communication protocol · next step

**Default rule:** Do not externally commit to scope/capacity/timeline before internal alignment.
**VN-GOV/Andrea:** Route via YiLun first. CC Peter if needed.

---

## Pattern Promotion Rule

Do not promote a new pattern unless it appears across **3+ distinct calendar days**, or severity >= 9 across 3+ days.
If insufficient: `No new pattern promoted — insufficient historical proof.`

---

## Top 5 Focus Rule

**Exactly 5 items.** No more, no fewer. Each must include:
- Priority number
- Action
- Owner
- Next step
- Deadline (absolute YYYY-MM-DD — never "tomorrow" or "next week")

---

## STEP 4 — WRITE-BACKS (after output, if write access available)

### 4A — Write intel_daily to knowledge_facts

```python
intel_daily_payload = {
    "tag": "intel_daily",
    "date": today,
    "feature_changes": [  # v9.2 — durable daily snapshot of feature movements
        {"feature_key": f["feature_key"], "status": f["status"],
         "signal": f.get("status_signal"), "summary": f.get("status_summary")}
        for f in feat_changed_today
    ],
    "version": 1,
    "context_source": ctx.get("source", "supabase"),
    "headline": "<1 sentence: most important thing today>",
    "top_decisions": all_decisions[:5],
    "blockers": [s["summary"] for s in cs_blockers],
    "scope_risks": [s["summary"] for s in cs_scope_risks],
    "open_actions": [a.get("title") for a in top_actions if a.get("status") not in ("done","cancelled")],
    "reply_queue_summary": {
        "pending": len(reply_queue_pending),
        "overdue": len(reply_queue_overdue),
        "human_review": len(reply_queue_human_review),
    },
    "missing_information": [],
    "patterns_promoted": [],
}
upsert_knowledge_fact(fact_type="intel_daily", payload=intel_daily_payload)
```

### 4B — Write risks (new/updated only)

For real delivery/scope/integration/governance risks only. Do not write transient noise.

### 4C — Write EOD context pack (feeds next morning's briefing)

```python
upsert_context_pack(pack_type="eod", payload={...})
print("[eod_context_pack_written_supabase] ✅")
```

### 4D — Weekly synthesis (Mondays only)

If today is Monday → synthesize last 7 `intel_daily` entries → write `intel_weekly` to `knowledge_facts`.

**Never write to Mem0.**

If write-back fails or is unavailable:
`Supabase write-back failed or unavailable — no Mem0 fallback used.`

---

## STEP 5 — WRITE ACTION LOG (always, silent)

```python
write_action(
    skill       = "EOD",
    action_type = "REVIEWED",
    summary     = f"EOD review complete — {len(all_decisions)} decisions, {len(cs_blockers)} blockers, {len(open_risks)} risks | context=supabase",
    metadata    = {
        "decisions":              len(all_decisions),
        "blockers":               len(cs_blockers),
        "risks":                  len(open_risks),
        "clickup_replies_needed": len(clickup_replies_needed),
        "patterns_promoted":      len(pattern_candidates_promoted),
        "weekly_ran":             (today_weekday == "Monday"),
        "eval_lessons_applied":   eval_prevention_rules_count,
        "context_source":         ctx.get("source","unknown"),
        "context_degraded":       ctx.get("degraded", False),
        "eod_pack_written":       bool(eod_pack_result),
    }
)
```

---

## STEP 6 — SELF-IMPROVE HOOK (final, auto — never skip)

This is what makes the operator self-training with **no manual trigger**. After the EOD
output is delivered and STEP 4C (context pack) + STEP 5 (action log) have run, invoke the
behavioral auto-train loop.

Read `/mnt/skills/user/omni-self-improve/SKILL.md` and execute it with:
```python
caller     = "EOD"
new_output = True          # this run just produced output → self-improve gate passes by construction
output_ref = {             # what self-improve inline-evaluates (STEP 1)
    "top_actions": all_decisions_and_actions_just_produced,
    "decisions":   all_decisions,
    "risks":       open_risks,
    "replies":     clickup_replies_needed,
    "eod_pack":    eod_pack_result,    # the context pack written at STEP 4C
}
```

self-improve will: light 5-check inline-eval → write one `operator_eval_reviews` row →
promote any ≥2× cluster to `operator_rule` (auto-applied at the **next** briefing/EOD
STEP 0A2, no human step) → drift audit (surface only) → flag structural candidates for
`omni-operator-learning`. Append its ~5-line compact output **below** the EOD output.

**Hook guardrails (fail-open, non-negotiable):**
- Behavioral tier only — self-improve NEVER edits SKILL.md and NEVER weakens governance
  (YiLun→Andrea routing, capacity protocol). It may reinforce them, never override.
- **Fail-open:** if self-improve errors or its tables are missing, print one line
  `self-improve hook skipped: <reason>` and finish cleanly. The hook must NEVER block,
  delay, or corrupt the EOD output itself.
- No double-run: if a `SELF_IMPROVE_RUN` action for caller="EOD" is already logged at or
  after this run's start timestamp, skip silently.



Warn clearly if:
- Latest sync is stale or incomplete
- Context pack is stale, missing, or had to be compiled temporarily
- Sources failed — name them in output header

Continue with available Supabase evidence. Never fall back to Mem0.

---

## Non-Negotiables

- Supabase first, always.
- Mem0 skipped and retired — zero reads, zero writes, zero fallbacks.
- Load eval lessons (STEP 0A) before any output.
- Do not invent facts.
- Do not silently mark decisions as confirmed.
- Do not duplicate the full ClickUp Reply Queue — max 5 items.
- Do not resolve risks without Supabase evidence.
- Do not make external scope/timeline/capacity commitments without internal alignment.
- Feature sections render from feature_rollup + actions audit only — never invent statuses.
- Candidate confirm/merge/reject requires Nghiem's explicit answer — never auto-confirm.
- Wrong auto-supersedes found in audit MUST be reopened and captured as operator_feedback.
- Top 5 Focus must contain exactly 5 actions with absolute dates.
- Every blocker must have owner, next step, and deadline.
- Patterns require 3+ distinct calendar days before promotion.
- Weekly synthesis runs only on Mondays.
- EOD context pack must be written to Supabase after output (STEP 4C).
- Self-improve hook (STEP 6) runs as the final step, fail-open — behavioral tier only, never edits skills, never blocks EOD output on failure.

---

## Log Tokens

| Token | Emitted when |
|---|---|
| `[eod_supabase_context_loaded]` | STEP 1 after get_context_pack() |
| `[eod_context_source_supabase]` | source=supabase AND degraded=false |
| `[eod_degraded_false]` | degraded=false confirmed |
| `[eod_context_pack_written_supabase]` | STEP 4C after successful upsert |
| `[eod_mem0_structured_cache_blocked]` | Confirmation at STEP 1 |

---

## Error Handling

| Scenario | Action |
|---|---|
| `get_context_pack()` degraded | Warn user, mark output DEGRADED, continue — no Mem0 fallback |
| Context pack fields empty | Use available fields, note gaps in Missing Information |
| DAILY entry already exists | UPDATE (increment version) — do not duplicate |
| Supabase EOD pack write fails | Log warning, output still shown in chat, continue |
| No decisions in context pack | Skip 2A silently, note "No decision signals today" |
| `open_risks` empty | Note "No new risks today" |
| Cache stale > 24h | Strong warning at top, recommend omni-data-sync before proceeding |
| Weekly synthesis < 3 daily entries | Run on available entries, note coverage gap |
| `merged_comment_signals` empty | Skip comment signal section — note in Missing Information |

---

## CHANGELOG

| Version | Change |
|---|---|
| v9.4 | **Decision dedup render filter** (2026-06-21). The pattern-mining decisions query (STEP 0, last-14-day scan) now adds `AND superseded_by IS NULL` so duplicates merged by omni-data-sync v12.5 STEP 7A-DEDUP no longer re-enter EOD frequency maps / pattern promotion. Pairs with omni-utils v11.2 (context-pack builder filter) — together they close the render path for the chronic SA-pricing/MM-deploy/ID-deploy duplicate-decision finding. Additive, non-destructive. Note: the existing STEP 2 supersede-audit on `actions.raw_json->>'superseded_by'` is the feature-rollup mechanism and is unaffected — this is the separate `decisions.superseded_by` column. |
|---|---|
| v9.3 | **Self-improve hook wired (P2).** New final STEP 6 invokes `omni-self-improve` (caller="EOD", new_output=True) after STEP 4C/STEP 5 — closes the behavioral auto-train loop with no manual trigger: inline-eval the EOD output → promote ≥2× clusters to `operator_rule` (live at next STEP 0A2). Fail-open (hook errors never block EOD output); behavioral tier only (never edits SKILL.md, never weakens governance); no double-run guard. Registered in omni-config §10 v1.7. |
| v9.2 | **Feature Rollup EOD duties** (2026-06-11). STEP 1A maps `feature_rollup`; new STEP 1D derives changed-today / conflicts / candidates + supersede audit query. Four new output sections: Feature Status Changes Today, Auto-Superseded Actions (audit, with reopen path + silent operator_feedback capture on wrong supersedes), ⚠️ Status Conflicts review (accept/dismiss), 🆕 Candidates confirm/merge/reject (daily registry-growth checkpoint). intel_daily payload gains feature_changes. Requires context pack from omni-data-sync v12.2. |
| v9.0 | **Merged: uploaded new logic + production guardrails.** Added STEP 0A eval lessons from `operator_eval_reviews` (last 3 records, extract prevention rules, apply to all ranking/detection/classification). Removed all Mem0 fallback paths — degraded=true now surfaces warning only. Removed all allowed/blocked Mem0 write references from GUARDRAILS section. Replaced with clean Non-Negotiables list. Added `eval_lessons_applied` to `write_action()` metadata. Top 5 Focus enforced at exactly 5 with absolute dates. Reply queue capped at max 5. Retained: Technical Assumptions section, Stakeholder Concerns section, write_action() STEP 5, upsert_context_pack("eod") STEP 4C, weekly synthesis on Mondays, pattern promotion rule. Output format reorganized to match uploaded spec (16 sections). |
| v8.0 | Supabase-only declared. Mem0 writes stated as retired. |
| v7.0 | Phase 4 — Supabase-first context loading. Blocked Mem0 structured cache tags. |
| v6.x | Unified decision tag, three-register routing, ownership fields. |
| v5.x | Reply Queue EOD Check, ClickUp Comment Signal integration. |
| v4.x | get_context_pack() refactor, auto FULL sync. |
| v3.0 | Live decision register via write_action(). |
| v2.0 | Severity-weighted pattern promotion. |
| v1.0 | Initial version. |
