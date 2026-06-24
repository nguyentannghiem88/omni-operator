---
name: omni-ai-operator-eval-review
version: "2.1"
description: "Review AI Operator output quality and write structured eval records to Supabase (table: operator_eval_reviews). v2.0: Supabase-only — Mem0 retired. Checks for: missed actions, wrong classifications, missing decision_status, stale context, wrong tone, and direct stakeholder questions without reply_required action. Triggers on: 'review AI output', 'eval review', 'check AI quality', 'run eval', 'quality check', 'check for mistakes', 'eval log'."
---

# OMNI AI Operator Eval Review — v2.1

## PURPOSE

Review AI Operator output for quality issues and write structured eval findings
to **Supabase** (`operator_eval_reviews` table).

**Mem0 is SKIPPED for eval records.** Do not write `[EVAL]` tags to Mem0.
**Source of truth for rules:** `/mnt/project/OMNI_AI_OPERATOR_EVALS.md`
**Do NOT append to that file** unless user explicitly says so.

---

## ⚠️ STORAGE RULE — SUPABASE ONLY

| Store | Role for Eval Records |
|---|---|
| **Supabase** | PRIMARY — all eval records written here |
| **Mem0** | SKIPPED — `mem0_status: "skipped"` on every record |

Never write `[EVAL][AI_OPERATOR]`, `[EVAL][WEEKLY]`, or any eval tag to Mem0.
If old Mem0 eval entries exist, ignore them — Supabase is the authoritative record.

---

## ⚠️ READ FIRST — SHARED CONFIG + UTILS

Before any step, read:
1. `/mnt/skills/user/omni-config/SKILL.md` → loads constants
2. `/mnt/skills/user/omni-utils/SKILL.md` → loads `write_action()`, `cache_check()`, `get_context_pack()`

---

## STEP 0 — IDENTIFY OUTPUT TO REVIEW

### 0A — Get current time
Call `user_time_v0` → extract `TODAY` (YYYY-MM-DD).

### 0B — Identify what output to review

Priority order:
1. **Inline in conversation** — user pasted or described the AI output → use directly
2. **Supabase context_pack** — call `get_context_pack()` → read fields:
   - `top_actions` → daily briefing / EOD action output
   - `decisions` → decision records to check classification
   - `open_risks` → risk records to check
   - `briefing_notes` → EOD review output
3. **User specifies which skill** — target that skill's Supabase source_items

### 0C — Load eval context
Read `/mnt/project/OMNI_AI_OPERATOR_EVALS.md` — extract:
- Issue type definitions
- Severity rules (P1/P2/P3/P4)
- Expected action fields
- Decision status taxonomy
- Expected behavior rules

### 0D — Read full Supabase context for today's eval

#### ⚠️ SQL PLACEHOLDER RULE — READ BEFORE EXECUTING ANY QUERY

Before executing any SQL, replace every placeholder with its real resolved value.
Never execute SQL containing raw placeholders.

| Placeholder | Replace with | Example |
|---|---|---|
| `TODAY` | Actual date string from STEP 0A | `'2026-05-27'` |
| `<current_review_type>` | Actual review type | `'daily'` |
| `<current_workflow>` | Actual skill/workflow name | `'omni-daily-briefing'` |
| `<target_output_date>` | Actual output date being evaluated | `'2026-05-27'` |
| `<prev_eval_id>` | UUID from prior query result | `'a1b2c3d4-...'` |

**Bad** (never execute):
```sql
WHERE review_date = TODAY
  AND evaluated_workflow = '<current_workflow>'
```

**Good** (always substitute first):
```sql
WHERE review_date = '2026-05-27'
  AND evaluated_workflow = 'omni-daily-briefing'
```

---

Execute all queries below via Supabase MCP `execute_sql`. This is mandatory —
eval review must validate against source-level proof, not only summarized context.

**① operator_eval_reviews — dedupe + rerun check**
```sql
SELECT id, review_date, review_type, evaluated_workflow, evaluated_output_date,
       run_sequence, overall_status, overall_score, created_at
FROM operator_eval_reviews
WHERE review_date = TODAY
  AND review_type = '<current_review_type>'
  AND evaluated_workflow = '<current_workflow>'
  AND evaluated_output_date = '<target_output_date>'
ORDER BY run_sequence DESC
LIMIT 5;
```
- If table does not exist → go to STEP 3A to create it first
- If rows found → this is a rerun — see STEP 3B dedupe logic
- Capture latest row's `id` as `prev_eval_id` and `run_sequence` as `prev_run_seq`

**② sync_runs — freshness + sync_run linkage**
```sql
SELECT id, started_at, completed_at, status, sync_mode
FROM sync_runs
ORDER BY started_at DESC
LIMIT 1;
```
→ Capture `id` as `evaluated_sync_run_id`. Check `completed_at` for staleness.

**③ context_packs — summarized context freshness**
```sql
SELECT id, created_at, source, degraded, top_actions, decisions, open_risks, briefing_notes
FROM context_packs
ORDER BY created_at DESC
LIMIT 1;
```
→ Used for CHECK 11 (stale context). If `degraded=true` → flag immediately.

**④ source_items — raw source evidence**
```sql
SELECT id, source_type, external_id, title, content, tags, created_at, updated_at
FROM source_items
WHERE updated_at >= (NOW() - INTERVAL '24 hours')
ORDER BY updated_at DESC
LIMIT 100;
```
→ Ground truth for CHECK 1 (missed actions), CHECK 10 (unsupported assumptions),
CHECK 12 (missing source). Cross-reference every action/decision against this.

**⑤ actions — action records to validate**
```sql
SELECT id, title, owner, priority, due_date, source, source_reference, confidence, status
FROM actions
WHERE created_at >= (NOW() - INTERVAL '24 hours')
ORDER BY priority ASC, created_at DESC;
```
→ Used for CHECK 1, 7, 8, 9, 12, 13, 15.

**⑥ decisions — decision records to validate**
```sql
SELECT id, title, decision_status, source, source_reference, confidence, created_at
FROM decisions
WHERE created_at >= (NOW() - INTERVAL '24 hours')
ORDER BY created_at DESC;
```
→ Used for CHECK 2, 3, 4. Every decision here is an entry for `decisions_checked`.

**⑦ risks — risk records to validate**
```sql
SELECT id, title, severity, owner, source, created_at
FROM risks
WHERE created_at >= (NOW() - INTERVAL '24 hours')
ORDER BY severity ASC, created_at DESC;
```
→ Used for CHECK 7, 12. Populate `risks_checked` in eval payload.

---

## STEP 1 — RUN EVAL CHECKS

For each check below, scan the output under review. Record every issue found.
If no issue found for a check → mark as PASS (do not fabricate issues).

### CHECK 1 — Missed Actions
**Criteria:** Action should exist when:
- Stakeholder asked Nghiem/team to do something
- A blocker requires follow-up
- A deployment/release risk exists
- A client question needs a response
- A commitment was made
- A dependency is waiting

**Flag:** `MISSED_ACTION` if such a signal is present in source but missing from action list.

### CHECK 2 — Wrong Decision Classification
**Criteria:** Decision status must match taxonomy exactly:
- `confirmed` → explicit approval/final agreement — **requires source evidence**
- `proposed` → suggested but not approved ("we could", "maybe", "I think")
- `pending` → waiting on stakeholder confirmation
- `rejected` → explicitly declined
- `unclear` → ambiguous signal

**Never treat `proposed`, `pending`, or `unclear` as `confirmed`.**
`confirmed` is only valid when a Supabase `source_items` record explicitly supports it.

**Flag:** `WRONG_CLASSIFICATION` if status is mismatched, with the source evidence (or lack of it).

### CHECK 3 — Proposed Treated as Confirmed
**Critical check.** For every decision in `decisions_checked`, verify:
1. Wording in the linked `source_items` record contains "suggest", "propose", "maybe",
   "could", "should we", "I think", "plan to", "intend to"
2. But `decision_status` was set to `confirmed`

**Flag:** `WRONG_CLASSIFICATION` at **P1** — this is the highest-risk decision error.
Evidence must include the exact source wording that contradicts `confirmed`.

### CHECK 4 — Missing decision_status / Incomplete decision record
**Criteria:** Every decision record in `decisions_checked` MUST contain all four fields:

```
decision_title:  <non-empty string>
decision_status: confirmed | proposed | pending | unclear | rejected
evidence:        <direct quote or source_item reference>
eval_result:     pass | fail | flag
```

**Flag:** `MISSING_DECISION_STATUS` at P2 for any decision missing any of these four fields.
**Flag:** `SOURCE_GAP` at P2 if `evidence` is empty or not traceable to a `source_items` record.

### CHECK 5 — Memory Noise
**Criteria:** Supabase/Mem0 entry is low-value if it:
- Contains transient data (e.g., "meeting at 2pm today")
- Contains status that will be stale in < 24h with no analytical value
- Duplicates information already in a higher-quality entry
- Contains vague non-actionable text

**Flag:** `MEMORY_NOISE` for entries that do not add long-term intelligence value.

### CHECK 6 — Duplicate Memory
**Criteria:** Two or more entries contain the same core content (same project, same signal, same action) under different tags or near-duplicate text.

**Flag:** `MEMORY_DUPLICATE` with both entry IDs if available.

### CHECK 7 — Wrong Priority
**Criteria:**
- P1 misclassified → item with real delivery/stakeholder/production risk marked P2 or lower
- P1 over-assigned → routine item marked P1 without justification

**Flag:** `WRONG_PRIORITY` with correct_priority suggestion.

### CHECK 8 — Wrong Owner
**Criteria:** Action assigned to person not responsible per OMNI team structure.

Known ownership rules:
- VN-GOV / Andrea capacity comms → YiLun only (Peter CC)
- HAP Myanmar → Kezia
- REP/LOOP → Dung Le / Phi / Tron
- PEM/Claims → Linh / Long Vo / Dung Thi
- ADO sync ownership → Nghiem + Huy Phan
- QA setup → Tron + Hien

**Flag:** `WRONG_OWNER` if action assigned to wrong person, with correct_owner suggestion.

### CHECK 9 — Wrong Due Date
**Criteria:**
- Due date is explicitly stated in source but output assigned different date
- Due date was invented with no source support
- Due date set to UNKNOWN when source clearly states deadline

**Flag:** `WRONG_DUE_DATE` with evidence from source.

### CHECK 10 — Unsupported Assumptions
**Criteria:** AI stated a fact, inferred an owner, or assigned a status not supported by any source in the output.

**Flag:** `UNSUPPORTED_ASSUMPTION` with the specific assumption and what was actually in the source.

### CHECK 11 — Stale Context
**Criteria:**
- AI used cache that was > 5h old without flagging it
- AI referenced a decision or status that was overridden in a newer source
- context_pack shows stale timestamp but AI did not warn user

**Flag:** `STALE_CONTEXT` with staleness age and impact.

### CHECK 12 — Missing Source
**Criteria:** Any action, decision, or blocker record is missing `source` or `source_reference` field.

**Flag:** `SOURCE_GAP` for each affected record.

### CHECK 13 — Missing Confidence
**Criteria:** Any action or finding with uncertainty (inferred, ambiguous signal) missing `confidence: low/medium/high`.

**Flag:** `MISSING_CONFIDENCE` for each affected record.

### CHECK 14 — Wrong Email/Comment Tone
**Criteria:** Drafted message contains:
- Overly casual tone to senior stakeholder (Andrea, Kay Sheng, Angelia)
- Overly formal/stiff tone for internal team
- Accusatory or defensive language
- Commitment made without validation
- Scope agreed without checking capacity

**Flag:** `WRONG_EMAIL_TONE` with specific lines causing concern.

### CHECK 15 — Direct Stakeholder Question Without reply_required
**Criteria:** Source (email, Teams, ClickUp) contains a direct question from a stakeholder to Nghiem or team, but no `reply_required: true` action was created.

Priority stakeholders: Andrea, Kay Sheng, Kezia, Angelia, Zach, Kinneth, Michelle Meng.

**Flag:** `MISSING_REPLY_REQUIRED` at P1/P2 depending on stakeholder seniority.

---

## STEP 2 — SCORE AND CLASSIFY

For each issue found, assign:

```
issue_id: EVAL-<TODAY_YYYYMMDD>-<NNN>   (sequential, 001, 002, ...)
issue_type: <from Issue Types in OMNI_AI_OPERATOR_EVALS.md>
severity: P1 / P2 / P3 / P4
skill_source: <which skill produced the output>
check_number: <1–15>
description: <what went wrong, 1–2 sentences>
evidence: <exact quote or reference from source>
correct_behavior: <what should have happened>
fix_action: <skill fix / system prompt update / rule update / no action needed>
status: open
```

**Severity quick guide:**
- P1 = delivery risk, client risk, wrong confirmed decision, production issue missed
- P2 = important action missing, wrong priority for sensitive item, missed direct question
- P3 = minor duplicate, minor summary issue, cosmetic owner/module error
- P4 = formatting, wording, non-blocking

---

## STEP 3 — WRITE EVAL RECORD TO SUPABASE

### 3A — Ensure table exists (with rerun columns)

If `operator_eval_reviews` table does not exist, run this DDL via Supabase MCP
(`apply_migration` or `execute_sql`):

```sql
create table if not exists public.operator_eval_reviews (
  id uuid primary key default gen_random_uuid(),
  review_date date not null,
  review_type text not null,
  evaluated_workflow text not null,
  evaluated_output_type text null,
  evaluated_output_date date null,
  evaluated_sync_run_id uuid null,
  overall_status text not null,
  overall_score numeric null,
  summary text not null,
  issues jsonb not null default '[]'::jsonb,
  blockers jsonb not null default '[]'::jsonb,
  decisions_checked jsonb not null default '[]'::jsonb,
  risks_checked jsonb not null default '[]'::jsonb,
  recommended_fixes jsonb not null default '[]'::jsonb,
  pattern_promotion_status text not null default 'not_promoted',
  pattern_promotion_reason text null,
  mem0_status text not null default 'skipped',
  mem0_note text not null default 'Mem0 skipped. Supabase is source of truth for OMNI eval records.',
  rerun_of_eval_id uuid null references public.operator_eval_reviews(id),
  run_sequence integer not null default 1,
  created_by text not null default 'claude',
  created_at timestamptz not null default now()
);
```

If table already exists, ensure rerun columns are present:

```sql
alter table public.operator_eval_reviews
  add column if not exists rerun_of_eval_id uuid null references public.operator_eval_reviews(id),
  add column if not exists run_sequence integer not null default 1;
```

### 3B — Same-day dedupe check + rerun logic

**Before building payload**, check STEP 0D query ① result:

| Scenario | Action |
|---|---|
| No existing row found | Insert as new — `run_sequence: 1`, `rerun_of_eval_id: null` |
| Row found, user did NOT request rerun | **Do not insert.** Notify user: "Eval record already exists for today (`id: <prev_eval_id>`, seq: <prev_run_seq>). Skipping insert. Use 'rerun eval' to force a new record." |
| Row found, user explicitly requested rerun | Insert new append-only row — `rerun_of_eval_id: <prev_eval_id>`, `run_sequence: <prev_run_seq + 1>` |

**Rerun detection:** user message contains "rerun", "re-run", "force eval", "run again", "re-eval".

### 3C — Build the eval payload

```json
{
  "review_date": "TODAY",
  "review_type": "daily" | "weekly" | "on_demand",
  "evaluated_workflow": "<skill name(s) reviewed>",
  "evaluated_output_type": "briefing" | "eod_review" | "ado_sync" | "email_extractor" | "requirement" | "other",
  "evaluated_output_date": "TODAY",
  "evaluated_sync_run_id": "<id from sync_runs query, or null>",
  "overall_status": "pass" | "issues_found" | "critical",
  "overall_score": "<0.0–1.0, derived: (15 - issues_found) / 15>",
  "summary": "<2–3 sentence plain text summary of overall quality>",
  "issues": [
    {
      "issue_id": "EVAL-YYYYMMDD-001",
      "issue_type": "...",
      "severity": "P1",
      "skill_source": "...",
      "check_number": 3,
      "description": "...",
      "evidence": "...",
      "correct_behavior": "...",
      "fix_action": "...",
      "status": "open"
    }
  ],
  "blockers": [],
  "decisions_checked": [
    {
      "decision_title": "<non-empty string>",
      "decision_status": "confirmed | proposed | pending | unclear | rejected",
      "evidence": "<direct quote or source_items id reference>",
      "eval_result": "pass | fail | flag"
    }
  ],
  "risks_checked": [
    {
      "risk_id": "<Supabase risks.id>",
      "title": "...",
      "severity": "...",
      "eval_result": "pass | flag"
    }
  ],
  "recommended_fixes": [
    {
      "skill": "<skill name>",
      "fix": "<rule update / prompt change / step rewrite>",
      "priority": "P1 | P2 | P3"
    }
  ],
  "pattern_promotion_status": "not_promoted",
  "pattern_promotion_reason": null,
  "mem0_status": "skipped",
  "mem0_note": "Mem0 skipped. Supabase is source of truth for OMNI eval records.",
  "rerun_of_eval_id": "<prev_eval_id or null>",
  "run_sequence": "<1 for first run, prev_run_seq+1 for rerun>",
  "created_by": "claude"
}
```

**overall_status logic:**
- Any P1 issue → `critical`
- Any P2 issue (no P1) → `issues_found`
- P3/P4 only → `issues_found`
- All checks pass → `pass`

**decisions_checked validation rule:**
- Every entry must have all 4 fields: `decision_title`, `decision_status`, `evidence`, `eval_result`
- `decision_status` must be one of: `confirmed`, `proposed`, `pending`, `unclear`, `rejected`
- Never set `eval_result: pass` if `decision_status` is `proposed`, `pending`, or `unclear`
  and the output treated it as confirmed — set `eval_result: fail` instead

### 3D — Write to Supabase

**If table exists and write permission available:**
```sql
INSERT INTO public.operator_eval_reviews (
  review_date, review_type, evaluated_workflow, evaluated_output_type,
  evaluated_output_date, evaluated_sync_run_id, overall_status, overall_score,
  summary, issues, blockers, decisions_checked, risks_checked, recommended_fixes,
  pattern_promotion_status, pattern_promotion_reason, mem0_status, mem0_note,
  rerun_of_eval_id, run_sequence, created_by
) VALUES (...);
```
Use Supabase MCP `execute_sql` tool.

**If write permission unavailable:**
Output the exact JSON payload and state:
> ⚠️ Supabase write-back unavailable. Please insert this payload manually into `operator_eval_reviews`.

**Do NOT write to Mem0.** Mem0 eval tags are permanently retired.

### 3E — Log eval completion via write_action()

Call `write_action()` from omni-utils:
- skill: `EVAL`
- action: `eval_review_completed`
- details: `"Reviewed: <skill_name> | issues: N | P1: N | P2: N | seq: <run_sequence> | Supabase: written"`

---

## STEP 3F — TREND SCORECARD (v2.1)

After the write, compute a 7-day learning trend:

```sql
-- Live schema: run_date (date), score (int), critical/high/medium_low_issues (int),
-- checks_passed (jsonb array of passed check names)
SELECT run_date, score,
       COALESCE(jsonb_array_length(checks_passed), 0) AS checks_passed_n,
       (critical_issues + high_issues + medium_low_issues) AS issues_found
FROM operator_eval_reviews
WHERE run_date >= CURRENT_DATE - INTERVAL '7 days'
ORDER BY run_date;
```

Derive `trend = improving | flat | degrading` (compare first vs last `score`).
Any check failing ≥2× in the window → flag as **recurring** with note:
"eligible for operator_rule promotion — run omni-operator-learning".

---

## STEP 4 — PRESENT FINDINGS TO USER

### If issues found:

```
## AI Operator Eval — [TODAY]
Reviewed: <skill_name>
Storage: Supabase → operator_eval_reviews ✓  (seq: <run_sequence>)
Decisions checked: N  |  Risks checked: N

### Issues Found: N (P1: N | P2: N | P3: N | P4: N)

| # | Issue ID | Type | Severity | Description | Fix |
|---|----------|------|----------|-------------|-----|
| 1 | EVAL-... | WRONG_CLASSIFICATION | P1 | ... | ... |
...

### Checks Passed: N/15  |  7-day trend: <improving|flat|degrading>
<list passed check names>
```

### If no issues found:

```
## AI Operator Eval — [TODAY]
Reviewed: <skill_name>
Storage: Supabase → operator_eval_reviews ✓  (seq: <run_sequence>)
Decisions checked: N  |  Risks checked: N

All 15 checks passed. No issues found.
Output quality: HIGH

Short summary: <2–3 sentences on what was checked and why output was clean>
```

### If dedupe blocked insert (no rerun requested):

```
## AI Operator Eval — [TODAY]
⚠️ Eval already exists for this workflow today (id: <prev_eval_id>, seq: <prev_run_seq>).

No new record inserted. To force a rerun, say "rerun eval".
Existing eval summary: <overall_status> | <issues_found> issues | P1: N
```

---

## STEP 5 — WEEKLY PATTERN PROMOTION (Monday only)

If today is Monday:
1. Query Supabase for last 7 days of eval records:
   ```sql
   SELECT issues FROM operator_eval_reviews
   WHERE review_date >= (TODAY - INTERVAL '7 days')
   ORDER BY review_date;
   ```
2. Unnest all `issues` arrays → count frequency of each `issue_type`
3. If any `issue_type` appears ≥ 3 times → flag as **recurring pattern**
4. INSERT a new `operator_eval_reviews` record with:
   - `review_type: "weekly"`
   - `summary` containing top 3 recurring issue types, affected skills, recommended fixes
   - `pattern_promotion_status: "promoted"`
   - `pattern_promotion_reason: "<issue_type> appeared N times in last 7 days"`
5. Surface to user: "Recurring pattern detected: <type> — recommend updating <skill>"

**Do NOT write weekly pattern to Mem0.**

---

## GUARDRAILS

- **Never invent issues** — only flag real evidence from the output under review
- **Never append to OMNI_AI_OPERATOR_EVALS.md** unless user explicitly requests it
- **No fake eval records** — if output is clean, write a clean PASS record, not fabricated issues
- **Dedupe enforced** — do not insert if same-day + same workflow + same output date row exists, unless rerun explicitly requested
- **Rerun = new append-only row** — never overwrite existing eval rows; set `rerun_of_eval_id` + increment `run_sequence`
- **P1 issues must have evidence** — no P1 without direct quote or source_items reference
- **Proposed ≠ Confirmed** — always P1 if confused; `confirmed` requires explicit Supabase source evidence
- **decisions_checked is mandatory** — every decision must have all 4 fields: `decision_title`, `decision_status`, `evidence`, `eval_result`
- **Allowed decision_status values only**: `confirmed`, `proposed`, `pending`, `unclear`, `rejected` — no other values
- **Missing source on P1/P2 action = SOURCE_GAP at P2**
- **Decision record missing any of 4 required fields = MISSING_DECISION_STATUS at P2**
- **Never read or write Mem0 for eval records** — `mem0_status` is always `"skipped"`
- **Read all 7 Supabase sources in STEP 0D** — do not skip source_items, actions, decisions, or risks
- Vietnamese-language outputs require same eval rigor as English
- Do not penalize AI for correctly flagging uncertainty — `confidence: low` is correct behavior, not a failure
