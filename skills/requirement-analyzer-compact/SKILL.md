---
name: requirement-analyzer-compact
version: "4.0"
description: "Convert emails, ClickUp tasks, Teams chats, and comments into concise business-focused requirements (70% business, 30% technical). v4.0: Supabase-only — Mem0 retired. Reads prior captures from Supabase actions. Writes requirements to knowledge_facts (fact_type=action_req) and actions. Reads signals from source_items (source_type=clickup_comment). Use for OMNI/OMS structured requirements."
---


# Requirement Analyzer (Compact)

## STEP 0 — CACHE CHECK

Call `get_context_pack("req_analysis")` from `omni-utils` SKILL.md.

```python
ctx = get_context_pack("req_analysis")
if ctx["needs_sync"]:
    print(f"⚠️ Cache stale/missing: {ctx['stale'] + ctx['missing']} — using available data")

emails    = ctx["data"].get("emails", [])          # email context for requirement source
teams     = ctx["data"].get("teams", [])           # teams context
clickup   = ctx["data"].get("clickup", {})         # existing task context
actions   = ctx["data"].get("actions", [])         # [ACTION][REQ] entries → prior captures
decisions = ctx["data"].get("intel_decision", [])  # past decisions affecting scope

# NEW v3.0 — ClickUp Comment Signals as requirement sources
comment_signals      = ctx["data"].get("comment_signals", [])
comment_signals_open = ctx["data"].get("comment_signals_open", [])
```

**Prior capture check**: query Supabase `actions` WHERE source LIKE 'req:%' from the last 14 days matching the same `module` + `opco` as the current input. Surface as "Prior Captures" at top of output. Do NOT re-fetch live data.

### 0A — Comment Signal Requirement Extraction (NEW v3.0)

Before processing the user's input, scan comment signals for requirement-relevant signal types.

```python
# Signal types that carry requirement information
REQ_SIGNAL_TYPES = {"REQUIREMENT_CHANGE", "CLARIFICATION", "SCOPE_RISK", "DECISION"}

# Merge batch + open signals, deduplicate
merged_cs = {
    (s["task_id"], s["signal_type"]): s
    for s in (comment_signals_open + comment_signals)
}.values()

# Filter to requirement-relevant signals
req_comment_signals = [
    s for s in merged_cs
    if s.get("signal_type") in REQ_SIGNAL_TYPES
]

if req_comment_signals:
    print(f"Comment signals with requirement value: {len(req_comment_signals)} found")
    print(f"  Types: {[s.get('signal_type') for s in req_comment_signals]}")
else:
    print("No requirement-relevant comment signals found in cache")
```

These signals will be used in STEP 1 as an additional requirement source alongside the user's direct input.

---

## STEP 1 — EXTRACT

From input (email / ClickUp task / Teams chat / mixed), identify:
- Business goal / intent
- Functional requirements
- Technical hints (API, logic, data format)
- Constraints (timeline, region, version)
- Dependencies + stakeholders

### 1A — Comment Signal Requirements (NEW v3.0)

If `req_comment_signals` is non-empty, treat each relevant signal as an additional requirement source:

```python
for cs in req_comment_signals:
    signal_type = cs.get("signal_type")
    task_name   = cs.get("task_name", "")
    summary     = cs.get("summary", "")
    author      = cs.get("comment_author", "unknown")

    if signal_type == "REQUIREMENT_CHANGE":
        # Treat as a requirement change — from/to format
        print(f"📋 Requirement change from comment on '{task_name}': {summary}")
        # → Add to extracted requirement list as CHANGED/NEW item

    elif signal_type == "CLARIFICATION":
        # Treat as expected behavior clarification — supplements existing requirement
        print(f"💡 Clarification from comment on '{task_name}': {summary}")
        # → Add as clarification note to relevant requirement

    elif signal_type == "SCOPE_RISK":
        # Treat as potential new requirement or scope expansion
        print(f"⚠️ Scope risk from comment on '{task_name}': {summary}")
        # → Flag as new requirement candidate with RISK tag

    elif signal_type == "DECISION":
        # Treat as confirmed expected behavior
        print(f"✅ Decision from comment on '{task_name}': {summary}")
        # → Add as confirmed requirement with DECISION source tag
```

**Source tagging rule:** Requirements extracted from comment signals must be tagged with:
- `source: CLICKUP_COMMENT`
- `task_id: <task_id>`
- `comment_author: <author>`
- `signal_type: <type>`

This allows downstream tracking of where each requirement originated.

---

## STEP 1B — DEDUP CHECK

Before writing output, query Supabase `actions` WHERE source LIKE 'req:%' last 14 days:
- Look for `req_id` entries with same `module` + `opco`
- If found: surface as **⚠️ Prior Capture** at top of output
- If the new requirement **supersedes** a prior one: note `supersedes: <req_id>`
- If it **duplicates** one: flag and ask user to confirm before writing new entry

**NEW v3.0**: Also check if any requirement extracted from comment signals was already captured from a prior email/Teams analysis for the same task. If so, mark as `supersedes` the prior capture.

---

## STEP 2 — INTERPRET (safe mode)
- Only infer when highly confident
- Flag unclear items — do NOT assume
- Remove noise (greetings, duplicates), merge overlapping points

**NEW v3.0**: When a comment signal and email/Teams input describe the same requirement:
- Merge into a single requirement
- Use the more specific/detailed description (usually comment signal has raw detail)
- Mark source as `MIXED` (both email/teams and comment)

---

## REQ_ID FORMAT

Every requirement gets a unique ID generated at capture time:
```
REQ-<OPCO>-<MODULE>-<YYYYMMDD>-<NNN>
```
Examples:
- `REQ-MY-REP-20260517-001`
- `REQ-ID-OMS-20260517-002`
- `REQ-ALL-LOOP-20260517-001` (multi-opco)

Sequence `NNN` increments per module+opco+date. Check `knowledge_facts` WHERE fact_type='action_req' AND fact_key LIKE '%{module}-{opco}-{date}%' for today's highest NNN before assigning.

---

## OUTPUT FORMAT

### ⚠️ Prior Captures (if any)
- `<req_id>` | <module>/<opco> | <date> | <summary> — [SUPERSEDED BY THIS / RELATED / DUPLICATE?]

### ⚠️ Comment Signal Sources (if any) ← NEW v3.0
- Task: `<task_name>` | Signal: `<signal_type>` | Author: `<author>` | Summary: `<summary>`
  → Requirement extracted: `<what was inferred>`

### Business Summary
- What is needed + why it matters

### Requirements

**Business**

| req_id | Description | Business value | Expected outcome | Status | Version | Source |
|---|---|---|---|---|---|---|
| REQ-XX-XX-YYYYMMDD-NNN | ... | ... | ... | new | 1 | email\|teams\|clickup_comment\|MIXED |

**Technical**
- Data/format | System behavior | Integration points

### Missing Information
- Clarification questions (do NOT skip this section)

### Actionable Steps
- Step-by-step execution plan

### Risks
- Key risks or edge cases

---

## RULES
- Compact mode: bullets only, no prose paragraphs
- 70% business / 30% technical focus
- ALWAYS include Missing Information + Actionable Steps
- ALWAYS generate req_id for every distinct requirement
- ALWAYS check for prior captures (STEP 1B) — never skip
- **NEW v3.0**: ClickUp comment signals are treated as equal-priority requirement sources to emails/Teams
- **NEW v3.0**: Always check `req_comment_signals` before STEP 1 — comment-sourced requirements may already answer the user's question
- **NEW v3.0**: Never discard a REQUIREMENT_CHANGE comment signal — always surface it, even if not directly related to the user's current input

---

## STEP 3 — UPDATE MEMORY (auto, silent — Supabase only)

For each requirement identified, write a structured row to `knowledge_facts`:

```python
upsert_knowledge_fact(
    fact_type = "action_req",
    fact_key  = req_id,                      # e.g. REQ-MY-OMS-20260610-001
    content   = {
        "version": <V>,
        "status": "<new|active|superseded>",
        "captured_at": "<YYYY-MM-DD HH:MM GMT+7>",
        "module": "<MODULE>", "opco": "<OPCO>",
        "source": "<EMAIL|TEAMS|CLICKUP|CLICKUP_COMMENT|MIXED>",
        "supersedes": "<prior_req_id or null>",
        "superseded_by": null,
        "comment_task_id": "<task_id if source=CLICKUP_COMMENT, else null>",
        "summary": "<≤60 chars business description>",
    },
)
```

- Upsert conflicts on `(fact_type, fact_key)` — re-capturing the same `req_id` increments version.
- If superseding a prior requirement: UPDATE the prior fact row → set `superseded_by:<new_req_id>`, `status:superseded`.
- Never duplicate req_ids.
- If module/opco context is unclear, set `opco:"UNKNOWN"` — do NOT omit.

---

## STEP 4 — WRITE ACTION LOG (always, silent)

Call `write_action()` from `omni-utils` SKILL.md. Do NOT skip this step.

```python
req_ids    = [<list of req_ids generated this run>]
req_count  = len(req_ids)
source     = "<EMAIL | CLICKUP | TEAMS | CLICKUP_COMMENT | MIXED>"
module     = "<REP | OMS | HAP | LOOP | PEM | TPM | None>"
opco       = "<MY | ID | KH | LA | MM | GR | ALL | None>"
top_req    = "<first business requirement in ≤60 chars>"
supersedes = "<req_id of superseded requirement, or None>"
# NEW v3.0
comment_signals_used = len([s for s in req_comment_signals if any(
    s.get("task_id") in r for r in req_ids
)])

write_action(
    skill       = "REQ",
    action_type = "CAPTURED",
    summary     = f"{req_count} requirement(s) captured — {top_req}",
    metadata    = {
        "source":                 source,
        "module":                 module,
        "opco":                   opco,
        "req_count":              req_count,
        "req_ids":                ",".join(req_ids),
        "supersedes":             supersedes,
        "comment_signals_used":   comment_signals_used,   # NEW v3.0
        "status":                 "active",
        "version":                1,
    }
)
```

---

## CHANGELOG

| Version | Change |
|---|---|
| v4.0 | **Supabase-only (Mem0 retired).** STEP 3 writes requirements to knowledge_facts (fact_type=action_req, fact_key=req_id) via upsert_knowledge_fact(). Prior-capture dedup reads knowledge_facts + actions tables. |
| v3.0 | **Phase 3 — ClickUp Comment Signal integration**: STEP 0 now loads `comment_signals` and `comment_signals_open` from `get_context_pack("req_analysis")`. Added STEP 0A: filters for REQ_SIGNAL_TYPES (REQUIREMENT_CHANGE, CLARIFICATION, SCOPE_RISK, DECISION). STEP 1 extended with STEP 1A: per-signal-type extraction logic with source tagging. STEP 1B dedup check extended to cross-reference comment-sourced reqs against prior captures. STEP 2 merge rule added for comment+email overlap. OUTPUT FORMAT: added "Comment Signal Sources" section, added "Source" column to requirements table. STEP 3 Mem0 format extended with `comment_task_id` field. STEP 4 write_action extended with `comment_signals_used` field. |
| v2.0 | Added req_id format (REQ-OPCO-MODULE-YYYYMMDD-NNN); version + status + superseded_by lifecycle fields; STEP 1B dedup check against prior [ACTION][REQ] entries; Prior Captures section in output; structured [REQ] Mem0 entries per requirement; write_action() updated with req_ids + supersedes fields. |
| v1.0 | Initial version: no req_ids, no versioning, no dedup. |
