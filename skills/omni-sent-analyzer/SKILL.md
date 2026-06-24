---
name: omni-sent-analyzer
version: "2.0"
description: "Analyze Sent emails and threads to learn Nghiem's communication style, commitments, decisions, and reusable drafting patterns. v2.0: Supabase-only — Mem0 retired. Writes to: user_preferences (comm style, stakeholder profiles), knowledge_facts (phrasebook, commitment, decision_sent, follow_up, thread_intel, stakeholder_pattern, project_pattern). Triggers on: 'analyze sent emails', 'learn my style', 'run sent analyzer', 'historical email scan', 'build style profile'."
---

# OMNI Sent Email Analyzer

**Purpose:** Extract structured intelligence from Nghiem's Sent emails to build an AI operating
memory — style profiles, stakeholder patterns, commitments, decisions, and reusable phrases.
The goal is NOT to copy the mailbox. The goal is to build intelligence that makes every future
email draft context-aware and personalized.

---

## ⚠️ READ FIRST — SHARED CONFIG + UTILS

**Before any step, read:**
1. `/mnt/skills/user/omni-config/SKILL.md` → loads constants (CONFIG_VERSION = "1.4")
2. `/mnt/skills/user/omni-utils/SKILL.md` → loads utilities (UTILITY_VERSION = "11.0")

---

## MODE DETECTION

Determine run mode from caller or user input:

| Mode | Trigger | Time range | Purpose |
|---|---|---|---|
| `DAILY` | Called from omni-data-sync STEP 2B / manual "analyze sent emails" | Last 24–72h (match inbox window) | Operational: commitments, follow-ups, decisions made today |
| `HISTORICAL` | "historical email scan", "build style profile", "learn my style", first-time setup | Last 3 months, processed in weekly batches | Style learning: profiles, phrasebook, stakeholder patterns |

---

## STEP 0 — CHECK EXISTING PROFILES (Supabase-only)

⛔ Mem0 is retired. All existing state is loaded from Supabase.

```python
# Load existing profiles and sent-intel facts from Supabase
global_style   = get_user_preference("comm_style_global", "nghiem:global")          # or None
sh_profiles    = supabase_sql("SELECT pref_key, content FROM user_preferences WHERE pref_type='stakeholder_profile';")
phrasebook     = get_knowledge_facts(fact_type="phrasebook")                         # fact_key='phrasebook:nghiem'
commitments    = get_knowledge_facts(fact_type="commitment")                         # fact_key='sent:commitments'
decisions_sent = get_knowledge_facts(fact_type="decision_sent")                      # fact_key='sent:decisions'
follow_ups     = get_knowledge_facts(fact_type="follow_up")                          # fact_key='sent:follow_ups'
thread_intel   = get_knowledge_facts(fact_type="thread_intel")                       # fact_key='sent:thread_intel'
sh_patterns    = get_knowledge_facts(fact_type="stakeholder_pattern")                # fact_key='stakeholder:{Name}'
pj_patterns    = get_knowledge_facts(fact_type="project_pattern")                    # fact_key='module:{Module}'
```

**DAILY mode:** Extract seen fingerprints from the `fps` array inside the `commitment` fact
(`fact_key='sent:commitments'`, content JSON field `"fps": [...]`). These are emails already
analyzed in prior runs. Any email whose fingerprint matches → skip in STEP 2. Do NOT skip the
entire run — only skip already-analyzed individual emails. Re-running the same day is safe.

**HISTORICAL mode:** If `user_preferences (pref_key='nghiem:global')` exists and was updated
< 7 days ago → ask user to confirm re-run. Re-run will MERGE, not overwrite.

```python
# DAILY — load seen fingerprints from Supabase commitment fact
seen_fps = set()
commitment_fact = next((f for f in commitments if f.get("fact_key") == "sent:commitments"), None)
if commitment_fact:
    seen_fps = set((commitment_fact.get("content") or {}).get("fps", []))
print(f"Sent dedup: {len(seen_fps)} fingerprints already seen — will skip these emails")
```

---

## STEP 1 — FETCH SENT EMAILS

Use `outlook_email_search` with folder filter `Sent Items` (or `from:me` equivalent).

### API call pattern:
```python
# M365 connector supports sent folder via folder parameter or from:me filter
sent_emails = outlook_email_search(
    folder="SentItems",          # or equivalent M365 folder param
    after=window_start,          # ISO datetime from caller or computed below
    limit=50,                    # max per page
)
# If folder param not supported, use: query="from:me" with date filter
```

**Time window:**
- DAILY: use `window_start` passed from caller (matches inbox window)
- HISTORICAL: compute batch range (see STEP 6 for batching logic)

**Pagination:** If result = 50, fetch page 2. Max 100 emails per batch.

---

## STEP 2 — FILTER: KEEP ONLY RELEVANT SENT EMAILS

**First: compute fingerprint for each email and skip already-seen ones (DEDUP).**

```python
def sent_fingerprint(email: dict) -> str:
    """Fingerprint = recipient_domains|subject_norm|date_YYYYMMDD"""
    to_domains = "|".join(sorted(set(
        e.split("@")[-1].lower()
        for e in (email.get("recipients") or [])
        if "@" in e
    )))
    subject_norm = re.sub(r'^(re:|fwd?:|fw:|\[external\])\s*', '', 
                          (email.get("subject") or "").lower().strip())
    date_str = (email.get("sentDateTime") or email.get("date") or "")[:10].replace("-", "")
    return f"{to_domains}|{subject_norm}|{date_str}"

new_emails = []
new_fps = []
for email in sent_emails:
    fp = sent_fingerprint(email)
    if fp in seen_fps:
        continue  # already analyzed in a prior run — skip
    new_emails.append(email)
    new_fps.append(fp)

print(f"Sent dedup: {len(sent_emails)} fetched → {len(new_emails)} new (skipped {len(sent_emails)-len(new_emails)} already-seen)")
# Continue filtering only new_emails below
sent_emails = new_emails
```

Apply ALL filters below. An email passes if it matches **at least one** INCLUDE rule and no EXCLUDE rule.

### INCLUDE when email matches any of:

**Recipient is a known stakeholder or project contact:**
- Andrea Cervellin, Kay Sheng Hong, Kezia Koen, Angelia Ooi, Zach / HtunKhaing Lynn
- Huy Phan, Ha Hoang Nguyen, YiLun, Peter
- Hung Nguyen, Hoang Ngo, Tan Vu, Michelle Meng, Kinneth Chhorn
- FieldAssist team (Achintya, Prithvi, Siddharth, Chitransh, Kartik)
- UB India team (Dhiraj, Deepak, Rittu)
- Any `@heineken.com` recipient
- Any `@niteco.se` recipient (internal senior — Canh, Cuong, etc.)

**Subject or body contains project/work keywords:**
- OMNI, OMS, REP, LOOP, HAP, PEM, ClickUp, ADO, JIRA
- timeline, release, deploy, estimate, governance, delivery
- requirement, scope, capacity, FTE, SOW, budget
- incident, blocker, issue, prod, UAT, QA, ACC

**Contains commitment language:**
- "I will", "we will", "I can", "we can"
- "by tomorrow", "by Friday", "by end of week", "next week", "by [date]"
- "I'll check", "we'll confirm", "I'll follow up", "will come back"
- "will share", "will send", "will provide", "will update"

**Contains decision language:**
- "we agreed", "confirmed", "decision", "finalized", "approved"
- "not proceed", "we should", "we suggest", "I suggest", "I recommend"
- "aligned on", "proceed with", "go ahead with"

**Contains pushback or diplomatic language:**
- "from delivery perspective", "to keep this lightweight"
- "to avoid", "I suggest we", "let's align", "before we commit"
- "concern", "risk", "impact", "dependency", "capacity constraint"

**Email body is substantive** (estimated > 80 words, or has numbered/bulleted content)

### EXCLUDE:

- Short replies: "Thanks", "Noted", "Got it", "OK", "Done", "Understood"
  → Filter: body < 30 words AND no commitment/decision language
- Meeting auto-responses, calendar invites
- System-generated emails (no-reply, automated, bounce)
- Newsletters or subscriptions
- Pure forwards with no added message from Nghiem
- Duplicate replies within the same thread (keep only the latest substantive reply)
- Personal/private/non-work emails
- HR-sensitive content (salary, performance review, personal matters)

---

## STEP 3 — THREAD-LINK: CONNECT SENT TO INBOX

For each filtered Sent email, attempt to find the corresponding Inbox email(s) from the same thread.

```python
# Use conversation_id or subject matching
for sent_email in filtered_sent:
    thread_id = sent_email.get("conversation_id") or normalize_subject(sent_email["subject"])
    inbox_match = find_in_inbox(thread_id)  # scan current inbox fetch or search by subject
```

**If inbox match found:** create a full thread record (incoming ask + my response).
**If no match:** analyze Sent email standalone (proactive outreach, internal coordination, etc.).

### Thread Intelligence Schema:

```json
{
  "thread_id": "<conversation_id or subject hash>",
  "thread_topic": "<1 sentence description>",
  "stakeholders": ["<name>"],
  "opco": "<MY|ID|KH|LA|TW|IN|MM|Regional|null>",
  "module": "<REP|OMS|HAP|LOOP|PEM|OMNI|null>",
  "incoming_ask": "<what was asked/requested/escalated — null if proactive>",
  "incoming_urgency": "<high|medium|low|null>",
  "my_response": "<what I said/decided/committed — ≤30 words>",
  "my_position": "<accepted|rejected|deferred|clarified|pushed_back|escalated|aligned>",
  "commitment_made": "<specific commitment or null>",
  "commitment_due": "<date or null>",
  "decision_communicated": "<decision text or null>",
  "follow_up_needed": "<what needs to happen next or null>",
  "follow_up_owner": "<Nghiem|other name|null>",
  "tone_used": "<direct|diplomatic|firm|friendly|neutral|urgent|careful>",
  "reusable_phrases": ["<phrase>"],
  "stakeholder_pattern_signal": "<observation about this stakeholder's behavior or null>",
  "risk_created": "<risk Nghiem's reply created or null>",
  "status": "<open|closed|watch>",
  "confidence": "<high|medium|low>"
}
```

---

## STEP 4 — BATCH LLM EXTRACTION

Run **one LLM extraction call** per batch of filtered Sent emails (max 20 per call).
Do NOT process one by one.

### Extraction prompt:

```
You are analyzing sent emails from Nghiem Tan Nguyen, Project Manager at Niteco for Heineken APAC.
Your goal: extract structured intelligence for building his communication style profile and operational memory.

DO NOT store raw email content. Extract only structured intelligence.
DO NOT invent commitments, dates, or decisions not actually present.
Mark confidence as "low" if you are inferring beyond what is clearly stated.

For each email, produce a JSON object with these fields:
{
  "sent_date": "<YYYY-MM-DD>",
  "recipient_names": ["<name>"],
  "thread_id": "<conversation_id or subject hash>",
  "topic": "<3-5 word topic>",
  "project": "<OMNI|OMS|REP|LOOP|HAP|PEM|Other>",
  "opco": "<MY|ID|KH|LA|TW|IN|MM|Regional|Unknown>",
  "communication_intent": "<commitment|decision|clarification|pushback|alignment|escalation|status_update|follow_up|risk_response|proactive>",
  "my_position": "<1 sentence: what position I took>",
  "commitment_made": "<specific commitment with due date if present, or null>",
  "decision_communicated": "<decision text or null>",
  "follow_up_needed": "<what Nghiem still needs to do, or null>",
  "follow_up_owner": "<Nghiem|name|null>",
  "tone_style": "<direct|diplomatic|firm|friendly|neutral|urgent|careful>",
  "reusable_phrases": ["<exact short phrase worth reusing in future emails>"],
  "stakeholder_signal": "<observation about stakeholder pattern, or null>",
  "risk_created": "<risk created by this reply, or null>",
  "confidence": "<high|medium|low>",
  "should_save": true
}

Rules for reusable_phrases:
- Only extract phrases that are genuinely reusable and reflect Nghiem's natural style
- Max 5 phrases per email
- Must be 3–15 words
- Examples: "From delivery perspective, ...", "To keep this lightweight, ...", "Let me check with the team and come back"
- Do NOT extract generic filler phrases

Rules for should_save:
- false: email is a short status update with no commitment, decision, follow-up, or style signal
- true: everything else that passed the Step 2 filter
```

---

## STEP 5 — WRITE TO SUPABASE

### 5A — Operational Intelligence (DAILY + HISTORICAL)

All sent intel is stored as aggregate `knowledge_facts` rows (conflict key: `(fact_type, fact_key)`).
Always MERGE new records with existing content — never full replace.

---

**Commitments → `upsert_knowledge_fact('commitment', 'sent:commitments', content)`**

Content JSON:
```json
{
  "updated_at": "<YYYY-MM-DD HH:MM GMT+7>",
  "version": <N+1>,
  "fps": ["<fp1>", "<fp2>", "..."],
  "records": [
    {"date":"<YYYY-MM-DD>","to":"<Stakeholder>","topic":"<topic>","commitment":"<what I promised>","due":"<date or TBD>","opco":"<opco>","status":"open"}
  ]
}
```

**Write logic:**
```python
existing = (commitment_fact or {}).get("content", {})
all_fps = sorted(set(existing.get("fps", [])) | set(new_fps))
merged_records = merge_records(existing.get("records", []), new_commitments)
# Remove commitments older than 30 days with status=closed; cap at 30 records
upsert_knowledge_fact("commitment", "sent:commitments", {
    "updated_at": now_str, "version": existing.get("version", 0) + 1,
    "fps": all_fps, "records": merged_records,
})
```
- Max 30 commitment records. Remove commitments older than 30 days with status=closed.
- Update status to `closed` when a follow-up confirms delivery.

---

**Decisions → `upsert_knowledge_fact('decision_sent', 'sent:decisions', content)` + `upsert_decisions()`**

```json
{"updated_at":"...", "version":<N>, "records":[
  {"date":"<YYYY-MM-DD>","to":"<Stakeholder>","topic":"<topic>","decision":"<what I communicated>","opco":"<opco>","module":"<module>"}
]}
```
- Decisions do not expire. ALSO call `upsert_decisions()` for each new decision
  (decision_key: `sent_email:<YYYY-MM-DD>:<decision_slug>`, status per content).

---

**Follow-ups → `upsert_knowledge_fact('follow_up', 'sent:follow_ups', content)`**

```json
{"updated_at":"...", "version":<N>, "records":[
  {"date":"<YYYY-MM-DD>","to":"<Stakeholder>","topic":"<topic>","follow_up":"<what I need to do>","owner":"<Nghiem|name>","due":"<date or TBD>","status":"open"}
]}
```
- Remove closed follow-ups older than 14 days. Mark `status:done` when resolved.

---

**Thread intel → `upsert_knowledge_fact('thread_intel', 'sent:thread_intel', content)`**

```json
{"updated_at":"...", "version":<N>, "threads":[ <thread intelligence JSON objects, schema from STEP 3> ]}
```
- Keep last 20 thread records. Oldest removed when > 20.
- DAILY mode: add new threads only. HISTORICAL: full rebuild.

---

### 5B — Style & Profile Memory (HISTORICAL mode — or when new pattern detected in DAILY)

---

**Supabase: upsert_user_preference('comm_style_global', 'nghiem:global', {...})**
```
content: {updated_at, source, version, tone, structure, length, opener, closer, patterns}
---JSON---
{
  "writing_style": "<2–3 sentences describing overall style>",
  "typical_structure": "<how emails are structured>",
  "sign_off": "Regards,\nNghiem",
  "greeting_pattern": "Hi @[Name],",
  "preferred_length": "<short|medium — max sentences>",
  "tone_default": "<diplomatic|direct|etc>",
  "avoids": ["<list of things Nghiem avoids in emails>"],
  "patterns": ["<observed recurring patterns>"],
  "diplomatic_triggers": ["<situations that trigger diplomatic mode>"],
  "version": <N>,
  "last_updated": "<YYYY-MM-DD>"
}
```
- One entry only. Always update (never duplicate).
- HISTORICAL: full rebuild from 3-month scan.
- DAILY: add `"recent_signal": "<observation>"` if new strong pattern detected.

---

**Supabase: upsert_user_preference('stakeholder_profile', 'nghiem:{Name}', {...})**
```
content: {name, updated_at, version, tone, formality, key_phrases, sensitivities}
---JSON---
{
  "stakeholder": "Andrea Cervellin",
  "role": "Senior Heineken Stakeholder",
  "email_frequency": "<how often Nghiem emails this person>",
  "typical_tone": "<tone Nghiem uses>",
  "typical_intent": ["<commitment|alignment|status_update|etc>"],
  "how_nghiem_handles_pressure": "<observation>",
  "how_nghiem_handles_scope_creep": "<observation>",
  "reusable_approach": "<1–2 sentences on how Nghiem typically engages>",
  "sensitivity": "<high|medium|low>",
  "governance_protocol": "<any special protocol, e.g. route through YiLun>",
  "sample_phrases": ["<phrase Nghiem uses with this person>"],
  "version": <N>,
  "last_updated": "<YYYY-MM-DD>"
}
```

**Auto-create a profile for any stakeholder Nghiem sent ≥ 2 emails to.**
Profiles never expire — update version and `last_updated` on each sync.

---

**Supabase: upsert_knowledge_fact('phrasebook', 'phrasebook:nghiem', {...})**
```
content: {updated_at, count, version, phrases: [...]}
---JSON---
{
  "diplomatic": [
    "From delivery perspective, ...",
    "To keep this lightweight, ...",
    "To avoid adding extra overhead, ..."
  ],
  "commitment": [
    "Let me check with the team and come back with a clear proposal.",
    "I'll confirm by [date]."
  ],
  "pushback": [
    "Before we commit the timeline, I suggest we first confirm the scope.",
    "We can support this, but we need to align the priority against the current committed backlog."
  ],
  "alignment": [
    "I suggest we use the existing checkpoint to track this topic.",
    "Let's align on the expected outcome first."
  ],
  "delivery_focus": [
    "This will help the team stay focused on delivery while still keeping visibility.",
    "From a delivery standpoint, ..."
  ],
  "sign_off_variants": [
    "Regards,\nNghiem"
  ]
}
```
- One entry. Merge new phrases on every update — never delete existing good phrases.
- Max 10 phrases per category. Replace low-quality with higher-quality.

---

**Stakeholder patterns → `upsert_knowledge_fact('stakeholder_pattern', 'stakeholder:{Name}', content)`**
```json
{
  "stakeholder": "Andrea Cervellin",
  "recurring_asks": ["<type of ask that keeps coming up>"],
  "pressure_patterns": ["<how this person applies pressure>"],
  "scope_signals": ["<phrases that signal scope creep>"],
  "preferred_response_style": "<what works well with this person>",
  "risk_flags": ["<things to watch for>"],
  "version": <N>,
  "last_updated": "<YYYY-MM-DD>"
}
```

---

**Project patterns → `upsert_knowledge_fact('project_pattern', 'module:{Module}', content)`**
```json
{
  "module": "OMS",
  "recurring_topics": ["<topics that keep appearing>"],
  "typical_stakeholders": ["<who is usually involved>"],
  "common_commitments": ["<types of commitments made>"],
  "common_risks": ["<risks that recur>"],
  "tone_typically_used": "<tone>",
  "version": <N>,
  "last_updated": "<YYYY-MM-DD>"
}
```

---

### 5C — Write Action Log

```python
write_action(
    skill       = "EMAIL",
    action_type = "SENT_ANALYSIS",
    summary     = f"Sent analyzer ({mode}) — {N_analyzed} emails analyzed | {N_commitments} commitments | {N_decisions} decisions | {N_followups} follow-ups",
    metadata    = {
        "mode":        mode,
        "emails_analyzed": N_analyzed,
        "commitments": N_commitments,
        "decisions":   N_decisions,
        "follow_ups":  N_followups,
        "profiles_updated": profiles_updated_list,
    }
)
```

---

## STEP 6 — HISTORICAL BATCH PROCESSING (HISTORICAL mode only)

Because 3 months of email can be large, process in **weekly batches**.

### Batch strategy:

```python
from datetime import datetime, timedelta

now = get_current_time_gmt7()
scan_start = now - timedelta(days=90)

batches = []
batch_start = scan_start
while batch_start < now:
    batch_end = min(batch_start + timedelta(days=7), now)
    batches.append((batch_start, batch_end))
    batch_start = batch_end

# Process each batch
for i, (start, end) in enumerate(batches):
    print(f"Processing batch {i+1}/{len(batches)}: {start.date()} → {end.date()}")
    sent_batch = fetch_sent_emails(start, end, limit=100)
    filtered = filter_relevant(sent_batch)           # STEP 2
    threaded = thread_link(filtered)                 # STEP 3
    extracted = batch_llm_extract(threaded)          # STEP 4
    update_supabase_operational(extracted)           # STEP 5A
    accumulate_style_signals(extracted)              # accumulate — do NOT write yet
    write_run_log(batch=i+1, ...)                    # write batch log

# After all batches: consolidate style signals → write style memory
consolidate_and_write_style_memory()                 # STEP 5B
```

### Deduplication across batches:
- Track `thread_id` set — skip threads already processed in earlier batches
- For same thread appearing across multiple weeks, keep only the latest reply per thread

### Consolidation rules (after all batches):
- `user_preferences` (pref_key=nghiem:global): synthesize from all observed patterns.
- `knowledge_facts` (fact_type=phrasebook): union of all extracted phrases, deduplicated.
- `knowledge_facts` (fact_type=stakeholder_pattern): merge all signals per stakeholder.
- `knowledge_facts` (fact_type=project_pattern): merge all signals per module.
- Stakeholder threshold: ≥ 2 emails sent to person → create/update profile.

---

## STEP 7 — WRITE RUN LOG (Supabase write_action only)

No separate run-log entry. The `write_action()` call in STEP 5C IS the run log
(skill=EMAIL, action_type=SENT_ANALYSIS, metadata carries mode, counts, warnings, errors).
For HISTORICAL mode add `batches: <N_total>` and `scan_range: last_3_months` to metadata.

---

## STEP 8 — RETURN SUMMARY

### DAILY mode output:
```
SENT EMAIL ANALYSIS — <datetime> GMT+7 | Mode: DAILY

📤 Analyzed: <N> sent emails | Filtered: <N>

📋 Commitments made: <N>
  - <stakeholder>: <commitment> (due: <date>)
  ...

🎯 Decisions communicated: <N>
  - <topic>: <decision>
  ...

🔄 Follow-ups created: <N>
  - <what> → owner: <owner>
  ...

⚠️ Risks from my replies: <list or "none">

Supabase: <N> knowledge_facts / user_preferences rows updated ✅
```

### HISTORICAL mode output:
```
HISTORICAL SENT EMAIL SCAN — <datetime> GMT+7
Scan range: last 3 months | Batches processed: <N>/<N>

📚 Intelligence built:
  - Global style profile: ✅ written
  - Stakeholder profiles: <N> (<names>)
  - Phrasebook: <N> phrases across <N> categories
  - Stakeholder patterns: <N>
  - Project patterns: <N>

📋 Operational findings:
  - Commitments: <N>
  - Decisions: <N>
  - Open follow-ups: <N>

Supabase: <N> rows written/updated ✅
Next recommended scan: <date + 30 days>
```

---

## INPUTS/OUTPUTS SUMMARY

| Input | Source |
|---|---|
| `mode` | Caller or user input |
| `window_start` | Passed from omni-data-sync (DAILY) or computed (HISTORICAL) |
| `existing_state` | Loaded from Supabase in STEP 0 |

| Output | Supabase target | Mode |
|---|---|---|
| Commitments | `knowledge_facts` commitment / sent:commitments | DAILY + HISTORICAL |
| Decisions | `knowledge_facts` decision_sent / sent:decisions + `decisions` table | DAILY + HISTORICAL |
| Follow-ups | `knowledge_facts` follow_up / sent:follow_ups | DAILY + HISTORICAL |
| Thread intel | `knowledge_facts` thread_intel / sent:thread_intel | DAILY + HISTORICAL |
| Global style | `user_preferences` pref_key=nghiem:global | HISTORICAL (+ DAILY if strong signal) |
| Per-stakeholder style | `user_preferences` pref_key=nghiem:{Name} | HISTORICAL (+ DAILY if new data) |
| Phrasebook | `knowledge_facts` fact_type=phrasebook | HISTORICAL (+ DAILY if new phrases) |
| Stakeholder patterns | `knowledge_facts` stakeholder_pattern / stakeholder:{Name} | HISTORICAL |
| Project patterns | `knowledge_facts` project_pattern / module:{Module} | HISTORICAL |
| Run log | `actions` table via write_action() | Both |

---

## PRIVACY & SAFETY RULES

- NEVER store raw email body content in Supabase facts.
- NEVER store HR-sensitive, medical, financial, or personal content.
- NEVER invent commitments, dates, or decisions not in the email.
- NEVER expose private diagnosis (e.g. "scope creep detected") in client-facing drafts.
- NEVER store sensitive personal emails unrelated to OMNI delivery work.
- If confidence = "low" → mark clearly; do not silently store uncertain data.
- Current thread facts ALWAYS override old style memory.
- If email is ambiguous → store with `confidence: low` and add to `warnings`.
- The goal is AI operating memory, not mailbox duplication.

---

## GUARDRAILS

- DAILY mode: run once per day per window. If already run for this window → skip.
- HISTORICAL mode: run once per month unless user explicitly triggers refresh.
- Never create duplicate fact rows — upserts conflict on (fact_type, fact_key); always merge with STEP 0 state.
- Stakeholder profile threshold: ≥ 2 emails → create profile. 1 email → skip profile.
- Phrasebook: never delete existing phrases in update — only ADD new ones or replace weak ones.
- Thread-link: if no inbox match found, analyze sent standalone. Never skip substantive sent emails.
- Batch size: max 20 emails per LLM extraction call. Split larger batches.
- Error in one batch → log, continue with next batch. Never abort full scan on single batch error.
- ⛔ Zero Mem0 calls. All writes via omni-utils Supabase helpers only.

---

## INTEGRATION WITH OTHER SKILLS

| Consumer skill | Uses |
|---|---|
| `draft-email-skill` | `user_preferences` (comm_style_global, stakeholder_profile), `knowledge_facts` (phrasebook, commitment, decision_sent, thread_intel) |
| `omni-daily-briefing` | `knowledge_facts` (commitment, follow_up, decision_sent) |
| `omni-eod-review` | All sent intel fact_types |
| `omni-data-sync` | Calls this skill as STEP 2B (DAILY) |
| `omni-utils` | `get_context_pack("email_draft_plus")` retrieves all sent intel tags |

---

## CHANGELOG

| Version | Change |
|---|---|
| v2.0 | **Supabase-only migration (Mem0 retired).** STEP 0 loads state from user_preferences + knowledge_facts; fingerprints from commitment fact `fps` array. STEP 5 writes via upsert_knowledge_fact()/upsert_user_preference()/upsert_decisions(). Bracket-tag Mem0 entries removed. Run log = write_action() only. Pinned to CONFIG 1.4 / UTILS 11.0. |
| v1.1 | **DEDUP FIX**: Added email-level fingerprint dedup for sent mail. STEP 0 now loads `fps:` field from existing `[COMMITMENT][SENT]` header (format: `domain\|subject_norm\|date`). STEP 2 computes fingerprint per email and skips already-analyzed ones before any filtering or LLM extraction. STEP 5A stores cumulative `fps:` in header on every write. Re-running the same day (or manually) is now safe — only truly new emails are processed. Removed the "< 2h → SKIP entire run" rule — replaced with per-email fingerprint check which is both more granular and more correct. |
| v1.0 | Initial version. DAILY + HISTORICAL modes. Thread-link logic. Batch processing for 3-month scan. Full Mem0 schema for all new tags. |
