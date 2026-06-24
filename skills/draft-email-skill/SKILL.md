---
name: draft-email-skill
version: "5.0"
description: "Draft professional emails for Nghiem (PM at Niteco, OMNI/Heineken APAC). v5.0: Supabase-only — reads stakeholder style profiles from Supabase user_preferences and knowledge_facts (phrasebook, commitment, thread_intel). Includes Diplomatic Mode and prior commitment conflict check. STEP 2C checks Supabase source_items (clickup_comment) for task context. ALWAYS use for any email task — new, reply, forward, follow-up, or escalation."
---


# Draft Email Skill

**Sender**: Nghiem Tan Nguyen | nghiem.nguyen@niteco.se | PM, Niteco
**Project**: OMNI/OMS platform for Heineken APAC (KH, Laos, ID, MM, MY, GR) — systems: OMNI, OMS, TPM, Loop, Basware/Heiflow, REP, PEM

---

## ⚠️ READ FIRST — SHARED CONFIG + UTILS

**Before any step, read:**
1. `/mnt/skills/user/omni-config/SKILL.md` → loads constants (CONFIG_VERSION = "1.4")
2. `/mnt/skills/user/omni-utils/SKILL.md` → loads utilities (UTILITY_VERSION = "11.0")

---

## STEP 0 — CACHE CHECK + STYLE CONTEXT LOAD

Call `get_context_pack("email_draft_plus")` from `omni-utils`.

```python
ctx = get_context_pack("email_draft_plus")
if ctx["needs_sync"]:
    print(f"⚠️ Cache stale/missing ({ctx['stale'] + ctx['missing']}) — using available data")
if ctx["sources_failed"]:
    print(f"⚠️ Partial sync detected: {ctx['sources_failed']}")

# Operational context
emails  = ctx["data"].get("emails", [])
teams   = ctx["data"].get("teams", [])
urgent  = ctx["data"].get("urgent", [])
actions = ctx["data"].get("actions", [])

# Style and intelligence context (from omni-sent-analyzer)
comm_style_global       = ctx["data"].get("comm_style_global")           # dict or None
comm_style_stakeholders = ctx["data"].get("comm_style_stakeholders", {}) # {name: dict}
phrasebook              = ctx["data"].get("phrasebook")                  # dict or None
commitments_sent        = ctx["data"].get("commitments_sent", [])
decisions_sent          = ctx["data"].get("decisions_sent", [])
follow_ups_sent         = ctx["data"].get("follow_ups_sent", [])
thread_intel            = ctx["data"].get("thread_intel")
stakeholder_patterns    = ctx["data"].get("stakeholder_patterns", {})
intel_risk              = ctx["data"].get("intel_risk", [])
intel_decision          = ctx["data"].get("intel_decision", [])

# NEW v4.0 — ClickUp Comment Signals for task context
comment_signals      = ctx["data"].get("comment_signals", [])       # latest batch
comment_signals_open = ctx["data"].get("comment_signals_open", [])  # all open/unresolved
```

**Profile availability check** (determine before STEP 2):
```python
target_recipient = "<extract from user request or thread To: field>"

has_style_profile = target_recipient in comm_style_stakeholders
has_sh_pattern    = target_recipient in stakeholder_patterns

if has_style_profile:
    print(f"✅ Style profile found for {target_recipient} — using learned tone")
else:
    print(f"⚠️ No style profile for {target_recipient} — using hardcoded tone rules as fallback")
```

---

## STEP 1 — CLASSIFY: REPLY or NEW

**REPLY**: Full thread provided or user says "reply to / respond to"
→ Read entire thread: who sent what, what's asked/escalated, pending actions, deadlines
→ Cross-check memory for related context (module, OPCO, known issues, deployment status)

**NEW**: Draft from scratch based on user's description.

⚠️ Current thread facts ALWAYS override old style memory. If facts changed, follow the thread.

---

## STEP 2 — TONE RESOLUTION (learned profile → hardcoded fallback)

Resolve tone in this priority order:

### Priority 1: Learned stakeholder profile (from omni-sent-analyzer)
If `has_style_profile`:
```python
profile      = comm_style_stakeholders[target_recipient]
tone_source  = "LEARNED"
tone_applied = profile.get("typical_tone", "diplomatic")
approach     = profile.get("reusable_approach", "")
sensitivity  = profile.get("sensitivity", "medium")
protocol     = profile.get("governance_protocol")   # e.g. "route through YiLun"
sample_phr   = profile.get("sample_phrases", [])
```

### Priority 2: Hardcoded tone table (fallback when no profile exists)
If `not has_style_profile`:
```python
tone_source = "HARDCODED_FALLBACK"

TONE_TABLE = {
    "Andrea":            {"tone": "formal, professional, concise",    "sensitivity": "high",   "protocol": "route through YiLun — Peter CC"},
    "Kay Sheng":         {"tone": "ultra-short, structured fields only", "sensitivity": "medium", "protocol": None},
    "Kezia":             {"tone": "formal, professional, concise",    "sensitivity": "medium", "protocol": None},
    "Angelia":           {"tone": "formal, warmer, relationship-aware","sensitivity": "medium", "protocol": None},
    "Zach":              {"tone": "formal, professional, concise",    "sensitivity": "medium", "protocol": None},
    "Huy Phan":          {"tone": "collaborative, peer-level, direct","sensitivity": "low",    "protocol": None},
    "Hung Nguyen":       {"tone": "collaborative, peer-level, direct","sensitivity": "low",    "protocol": None},
    "Hoang Ngo":         {"tone": "collaborative, peer-level, direct","sensitivity": "low",    "protocol": None},
    "Ha Hoang":          {"tone": "collaborative, peer-level, direct","sensitivity": "low",    "protocol": None},
    "Gandi":             {"tone": "formal, warmer, relationship-aware","sensitivity": "medium", "protocol": None},
    "Ratanak":           {"tone": "formal, warmer, relationship-aware","sensitivity": "medium", "protocol": None},
    "ZinZin":            {"tone": "formal, warmer, relationship-aware","sensitivity": "medium", "protocol": None},
    "CloudOps_default":  {"tone": "ultra-short, structured fields only","sensitivity": "low",  "protocol": None},
    "dev_team_default":  {"tone": "action-focused, short, @Name, minimal pleasantries","sensitivity": "low","protocol": None},
    "external_default":  {"tone": "professional, clear technical details","sensitivity": "medium","protocol": None},
}

matched = TONE_TABLE.get(target_recipient, TONE_TABLE["external_default"])
tone_applied = matched["tone"]
sensitivity  = matched["sensitivity"]
protocol     = matched["protocol"]
```

### Mixed audience rule:
Multiple recipients → use most formal/sensitive tone present across all recipients.

---

## STEP 2B — DIPLOMATIC MODE CHECK

Call `diplomatic_mode()` from `omni-utils` when ANY of these are true:

- Recipient is senior client/stakeholder (Andrea, Kay Sheng, Kezia, Angelia, Zach)
- Topic contains: governance, timeline, capacity, scope, resource, risk, delivery, approval, escalation
- User says: "push back", "decline", "diplomatic", "careful", "sensitive", "political"
- Active commitments or decisions conflict with this email's purpose
- Stakeholder pattern shows history of scope pressure or governance asks

```python
diplomatic_triggered = False
diag = {}

if should_trigger_diplomatic_mode(target_recipient, topic, user_intent):
    situation_map = {
        "governance": "governance_overhead",
        "scope":      "scope_creep",
        "timeline":   "timeline_pressure",
        "capacity":   "capacity_constraint",
        "risk":       "delivery_risk",
        "ownership":  "ownership_ambiguity",
    }
    situation = next((v for k, v in situation_map.items() if k in topic.lower()), "client_pressure")

    diag = diplomatic_mode(
        situation = situation,
        context   = {"stakeholder": target_recipient, "topic": topic, "risk_level": sensitivity}
    )
    diplomatic_triggered = True
```

**In STEP 6 output:**
- Show `private_diagnosis` as a NOTE in chat — NEVER in the email body
- Apply `use_phrases` naturally in the draft
- Validate draft does NOT contain any `avoid_phrases` before returning

---

## STEP 2C — PRIOR COMMITMENT, DECISION & COMMENT SIGNAL CHECK

Scan context for history relevant to this email:

```python
relevant_commitments = [c for c in commitments_sent
    if target_recipient.lower() in c.lower() or topic.lower() in c.lower()]

relevant_decisions   = [d for d in decisions_sent
    if target_recipient.lower() in d.lower() or topic.lower() in d.lower()]

relevant_followups   = [f for f in follow_ups_sent
    if target_recipient.lower() in f.lower() or topic.lower() in f.lower()]

if relevant_commitments:
    print(f"📋 Prior commitments to {target_recipient}: {relevant_commitments}")
if relevant_decisions:
    print(f"🎯 Prior decisions on this topic: {relevant_decisions}")
if relevant_followups:
    print(f"🔄 Open follow-ups: {relevant_followups}")
```

### NEW v4.0 — ClickUp Comment Signal Context Check

After scanning sent intel, also scan `comment_signals` and `comment_signals_open` for task-related signals relevant to this email's topic.

**Why**: Email replies about specific tasks may be inaccurate if we don't know the current comment-level state of those tasks (e.g., task shows "Done" in ClickUp but a comment says there's a blocker, or a stakeholder asked a question in a comment that hasn't been answered).

```python
# Build keyword set from email topic for matching
topic_keywords = set(topic.lower().split())
# Also extract OPCO codes and module names if present in topic
topic_opcos   = [o for o in ["my", "id", "kh", "la", "tw", "in", "mm"] if o in topic.lower()]
topic_modules = [m for m in ["rep", "loop", "hap", "pem", "oms", "cc", "omni"] if m in topic.lower()]

# Merge batch + open signals, deduplicate
merged_cs = {
    (s["task_id"], s["signal_type"]): s
    for s in (comment_signals_open + comment_signals)
}.values()

# Filter: signals relevant to this email's topic
EMAIL_RELEVANT_TYPES = {
    "BLOCKER", "STATUS_MISMATCH", "FOLLOW_UP", "CLIENT_CONCERN",
    "COMMITMENT", "DECISION", "REQUIREMENT_CHANGE", "SCOPE_RISK"
}

def cs_matches_topic(sig: dict) -> bool:
    """Returns True if the comment signal is topically relevant to this email."""
    task_name = (sig.get("task_name") or "").lower()
    sig_opco  = (sig.get("opco") or "").lower()
    sig_mod   = (sig.get("module") or "").lower()
    sig_sum   = (sig.get("summary") or "").lower()

    # Direct keyword match in task name or summary
    if any(kw in task_name or kw in sig_sum for kw in topic_keywords if len(kw) > 3):
        return True
    # OPCO match
    if topic_opcos and sig_opco in topic_opcos:
        return True
    # Module match
    if topic_modules and any(m in sig_mod for m in topic_modules):
        return True
    return False

relevant_comment_signals = [
    s for s in merged_cs
    if s.get("signal_type") in EMAIL_RELEVANT_TYPES and cs_matches_topic(s)
]

comment_signals_used = len(relevant_comment_signals)

if relevant_comment_signals:
    print(f"💬 Comment signals relevant to this email: {comment_signals_used}")
    for cs in relevant_comment_signals[:5]:  # show top 5 in internal note
        print(f"  [{cs.get('signal_type')}] {cs.get('task_name')}: {cs.get('summary')}")
```

**Rules for using comment signal context:**
- `BLOCKER` found on a task mentioned in this email → flag in NOTE (STEP 6): "Task X has a BLOCKER per recent comment — verify before confirming status"
- `STATUS_MISMATCH` → flag in NOTE: "ClickUp shows X but comment suggests different state — verify before sending"
- `FOLLOW_UP` where recipient = comment_author → acknowledge the question in the draft if appropriate
- `CLIENT_CONCERN` → trigger Diplomatic Mode (same as STEP 2B)
- `COMMITMENT` → treat like a prior_commitment: do NOT contradict without explicit user override
- `DECISION` → treat like a prior_decision: reference naturally if relevant
- `REQUIREMENT_CHANGE` or `SCOPE_RISK` → flag in NOTE: "There is a scope change/risk in comments — confirm current scope before sending"
- NEVER include raw comment text in the email body — always paraphrase into professional language
- NEVER expose internal comment signal data to the email recipient

```python
# Set flags for STEP 6 output note
cs_has_blocker     = any(s.get("signal_type") == "BLOCKER" for s in relevant_comment_signals)
cs_has_mismatch    = any(s.get("signal_type") == "STATUS_MISMATCH" for s in relevant_comment_signals)
cs_has_scope_risk  = any(s.get("signal_type") in ("REQUIREMENT_CHANGE","SCOPE_RISK") for s in relevant_comment_signals)
cs_has_concern     = any(s.get("signal_type") == "CLIENT_CONCERN" for s in relevant_comment_signals)

if cs_has_concern and not diplomatic_triggered:
    # Auto-trigger Diplomatic Mode if CLIENT_CONCERN found in comments
    diag = diplomatic_mode(
        situation = "client_pressure",
        context   = {"stakeholder": target_recipient, "topic": topic, "risk_level": sensitivity}
    )
    diplomatic_triggered = True
    print(f"⚠️ Diplomatic Mode auto-triggered via CLIENT_CONCERN comment signal")
```

**Rules for sent intel (unchanged from v3.0):**
- Prior commitment exists → do NOT contradict it unless user explicitly overrides.
- Prior decision exists → reference naturally in the draft when relevant.
- Open follow-up on same topic → acknowledge it if it adds value.
- Current thread ALWAYS overrides old memory if facts changed.

---

## STEP 3 — EMAIL TYPE + PHRASEBOOK APPLICATION

**Phrasebook application (if available):**
```python
if phrasebook:
    category_map = {
        "commitment":     phrasebook.get("commitment", []),
        "pushback":       phrasebook.get("pushback", []),
        "alignment":      phrasebook.get("alignment", []),
        "diplomatic":     phrasebook.get("diplomatic", []),
        "delivery_focus": phrasebook.get("delivery_focus", []),
    }
    # Use relevant phrases naturally — do not force-insert phrases that change meaning
```

**TYPE 1 — Deployment (CloudOps)**
```
Hi @CloudOps,
Please help schedule [SYSTEM + OPCO] production deployment.
[If hotfix: This is a hotfix for [OPCO]. Confirmed with @[contact].]
Date: [Day] ([D/Mon]) at [time] VN time.
Package: Will be confirmed before deployment.
Regards, Nghiem
```
Subject: `[[SYSTEM OPCO]] PROD deployment [D/Mon]`

**TYPE 2 — Reschedule**: `As [reason], please reschedule to [new date/time].`

**TYPE 3 — Deployed/Ready**: `[Feature] was deployed to [env]. Please check and let me know.`

**TYPE 4 — Status Update**: `[Short status — done / in progress / next.] [If action needed: Please [action].]`

**TYPE 5 — Escalation**: `[Issue clearly described.] Could you [confirm/clarify/prioritize]?`

**TYPE 6 — Internal Task**: `@[Name] — [what to do / check / follow up]. [Ticket ref if any.]`

**TYPE 7 — Follow-up**: `Hope you're doing well. Could you give us an update on this?` *(Heineken/external only — skip pleasantry for internal)*

**TYPE 8 — Technical/API**: `Please find [description] in the attached file. [If partial: For [X], will share [Y] later.]`

**TYPE 9 — Access/IT**:
```
Hi [IT],
Please [add/reset/provide access for]: [email] to [system]. Permission: [level].
Regards, Nghiem Nguyen / PROJECT MANAGER
```

**TYPE 10 — Approval/Ack**: `Approved.` / `Got it.` / `Noted.`

**TYPE 11 — FYI Forward**: `FYI` + 1-sentence context if needed. No greeting/sign-off.

**TYPE 12 — Introduction**: `[Purpose]. Please find [what] in the attached file.`

---

## STEP 4 — SUBJECT LINE
- Reply → keep existing subject with `Re:` prefix
- New → auto-tag: `[OMNI]`, `[OMNI ID]`, `[OMS KH]`, `[TPM]`, `[Claim]`, `[OMNI B2B]`, `[OMNI - GR]`, `[OMS]`

---

## STEP 5 — HARD STYLE RULES
1. Sign-off: always `Regards,\nNghiem` (IT requests: add `Nghiem Nguyen\nPROJECT MANAGER`)
2. Greeting: `Hi @[Name],` — never "Dear", never "Hi Team"
3. Body: max 4–6 sentences. Use numbered lists if more detail needed.
4. No filler: never "I hope this email finds you well", "Kindly", "As per my last email", "Please do not hesitate"
5. English only. No emojis. No exclamation marks.
6. Attachments: "Please find [description] in the attached file" — never just "see attached"
7. If diplomatic mode active: verify no `avoid_phrases` appear before finalizing.
8. **NEW v4.0**: If `cs_has_blocker` or `cs_has_mismatch` → do NOT confirm task completion or status without flagging the discrepancy to the user first (in NOTE, never in email body)

---

## STEP 6 — OUTPUT FORMAT

```
**Subject**: [subject]
**To**: [recipients]
**CC**: [if applicable]
---
[body]
```

**Note (shown in chat, never in email):**
```
Tone source: {tone_source} (LEARNED | HARDCODED fallback) | Tone: {tone_applied}
Profile used: {has_style_profile} | Stakeholder pattern: {has_sh_pattern}
Prior commitments surfaced: {len(relevant_commitments)}
Prior decisions surfaced: {len(relevant_decisions)}
Diplomatic mode: ACTIVE — {diag.get("private_diagnosis", "")} | OFF
Phrasebook: {phrasebook is not None}

Comment signal context ({comment_signals_used} relevant signals):  ← NEW v4.0
  ⚠️ BLOCKER detected: {cs_has_blocker} — verify task status before confirming
  ⚠️ Status mismatch: {cs_has_mismatch} — confirm actual state before sending
  ⚠️ Scope risk: {cs_has_scope_risk} — confirm scope before committing
  [list top 3 relevant comment signals with task name + summary]
```
(Only show comment signal section if `comment_signals_used > 0`)

If 2 valid strategic approaches exist → offer both with labels.

---

## STEP 7 — UPDATE MEMORY (auto, silent — Supabase only)

Scan email/thread for new durable info. Write to Supabase without asking:
- New contacts (name, email, role, OPCO) → `upsert_user_preference('stakeholder_profile', 'nghiem:{Name}', {...})`
- New requirements → `upsert_knowledge_fact('action_req', '<req_id>', {...})`
- Confirmed decisions → `upsert_decisions()` | New blockers/risks → `upsert_risks()`
- Deadlines / pending actions assigned to Nghiem → `write_action()` (status=open)

Upserts conflict on their natural keys — updating existing rows is automatic.
End output with:
`📝 Memory updated: [1-line summary]` or `📝 Memory: No new info.`

---

## STEP 8 — WRITE ACTION LOG (always, silent)

Call `write_action()` from `omni-utils`. Do NOT skip.

```python
write_action(
    skill       = "EMAIL",
    action_type = "SENT",
    summary     = f"{email_type} email drafted — to {recipient_name} re: {subject_tag}",
    metadata    = {
        "recipient":              recipient_name,
        "email":                  recipient_email,
        "module":                 module,
        "opco":                   opco,
        "type":                   email_type,
        "tone_source":            tone_source,
        "diplomatic":             diplomatic_triggered,
        "comment_signals_used":   comment_signals_used,   # NEW v4.0
    }
)
```

---

## CHANGELOG

| Version | Change |
|---|---|
| v4.0 | **Phase 3 — ClickUp Comment Signal context**: STEP 0 now loads `comment_signals` and `comment_signals_open` from `email_draft_plus` context pack. STEP 2C extended: after scanning sent intel, also scans merged comment signals for task-relevant signals using keyword/OPCO/module matching. Surfaces top 5 matches internally. Sets 4 flags (cs_has_blocker, cs_has_mismatch, cs_has_scope_risk, cs_has_concern) used in STEP 5 and STEP 6. CLIENT_CONCERN signal auto-triggers Diplomatic Mode. STEP 5 extended with rule 8: do not confirm completion/status when BLOCKER or STATUS_MISMATCH signal found. STEP 6 extended with comment signal context block in NOTE. STEP 8 write_action extended with `comment_signals_used` field. Utility version bumped to 6.0. |
| v5.0 | **Supabase-only (Mem0 retired).** STEP 0/2C read style + sent intel from user_preferences/knowledge_facts. STEP 7 writes via Supabase upsert helpers. Pinned CONFIG 1.4 / UTILS 11.0. |
| v4.0 | ClickUp Comment Signal context in STEP 0 + STEP 2C (source_items, source_type=clickup_comment). |
| v3.0 | Upgraded context pack to `email_draft_plus` (STEP 0). Tone resolution: learned profiles as primary, hardcoded rules as fallback (STEP 2). Added STEP 2B: Diplomatic Mode via `diplomatic_mode()` from omni-utils. Added STEP 2C: Prior commitment/decision conflict check from sent intel Mem0. Added phrasebook application in STEP 3. Updated output (STEP 6) to show style context. Action log metadata extended with `tone_source` and `diplomatic` fields. |
| v2.0 | STEP 0 refactored to use `get_context_pack("email_draft")`. Adds `actions` data for same-day email dedup. |
| v1.0 | Initial version. |
