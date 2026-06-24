---
name: omni-email-extractor
version: "4.0"
description: "Fetch and extract Outlook emails for OMNI. Called by omni-data-sync STEP 2. Also triggers on: 'extract emails', 'process emails', 'fetch email data'. v4.0: Supabase-only — Mem0 retired. Returns structured NormalizedSignal records to caller for Supabase upsert. STEP F optional writes go to Supabase: risks→risks, decisions→decisions, patterns→knowledge_facts, comm style→user_preferences. Does NOT write to Mem0."
---

# OMNI Email Extractor
**v3.0** — Phase 2B (Supabase migration) + fingerprint patch

Standalone email fetch + extraction skill for Nghiem Tan Nguyen.  
Called by `omni-data-sync` STEP 2. Returns structured records to caller for Supabase upsert.  
**Does NOT write email-list/structured cache anywhere — Mem0 retired; source_items upsert is handled by the caller.**

---

## INPUTS (passed from omni-data-sync or resolved locally)

| Parameter | Source | Required |
|---|---|---|
| `window_start` | Passed from omni-data-sync STEP 1 (ISO datetime) | Yes |
| `window_label` | Passed from omni-data-sync STEP 1 | Yes |
| `current_time` | Passed or fetch via `user_time_v0` if running standalone | Yes |
| `existing_fps` | Set of fingerprints already in Supabase `source_items` — passed by omni-data-sync | Production only |
| `force_reprocess` | Boolean — if true, emit action/decision/risk records even for SEEN emails | Optional, default false |

**Standalone mode** (not called from omni-data-sync):
- Fetch current time via `user_time_v0`; default `window_start` = current time − 18h
- `existing_fps` = not provided → all emails get `dedup_status = "unknown_standalone"`
- `force_reprocess` = false

**Production mode** (called from omni-data-sync):
- `existing_fps` MUST be passed by caller from Supabase `source_items` (keyed by fingerprint)
- Extractor must NOT read any legacy Mem0 cache for dedup under any circumstances (Mem0 retired)

---

## STEP A — FETCH EMAILS

Use `outlook_email_search` with the provided `window_start`.

### Priority filter (apply in order):
1. **Unread** OR **directly addressed to Nghiem** (To/CC)
2. **From priority senders** (always include regardless of read status):
   - Andrea Cervellin, Kay Sheng Hong, Kezia Koen, Angelia Ooi, Zach / HtunKhaing Lynn
   - Michelle Meng, Kinneth Chhorn, Tan Vu, Hung Nguyen, Hoang Ngo, Huy Phan
   - Achintya, Prithvi, Siddharth, Chitransh (FieldAssist), Kartik (ParallelDots)
   - Dhiraj Ippili, Deepak Jain, Rittu T Varghese (UB India)
3. **Subject keyword match** (include regardless of sender):
   - `urgent`, `blocker`, `down`, `prod issue`, `decision`, `approve`, `deploy`
   - `Malaysia`, `MY`, `MYS`, `Indonesia`, `MBI`, `CHUB`, `Customer Module`
   - `FieldAssist`, `IR SDK`, `scope`, `capacity`, `SOW`, `FTE`, `estimate`

Fetch up to **50 emails** per run. If result = 50, log `⚠️ email cap reached — consider narrowing window`.  
**Pagination**: if cap hit, fetch page 2 before dedup. Max 2 pages (100 emails total cap).

---

## STEP B — FINGERPRINT + DEDUP

For each email, compute a **fingerprint**:
```
fingerprint = sender_email_domain + "|" + subject_normalized + "|" + date_YYYYMMDD
```

### Subject normalization rules (applied in order):

**Step 1 — Detect and record `event_state` before stripping:**

| Subject prefix (case-insensitive) | `event_state` value |
|---|---|
| `Canceled:` or `Cancelled:` | `"canceled"` |
| `Updated:` | `"updated"` |
| `Rescheduled:` | `"rescheduled"` |
| _(none of the above)_ | `"normal"` |

**Step 2 — Strip reply/forward prefixes only** (do NOT strip event-state prefixes):
- Strip: `re:`, `fw:`, `fwd:`, `[external]`
- **Do NOT strip**: `canceled:`, `cancelled:`, `updated:`, `rescheduled:`

**Step 3 — Finalize:** lowercase the result, trim whitespace.

**Test case (required):**
```
"Canceled: catchup on malaysia deployment"
  → event_state = "canceled"
  → subject_normalized = "canceled: catchup on malaysia deployment"
  → fingerprint = "heineken.com|canceled: catchup on malaysia deployment|20260526"

"catchup on malaysia deployment"
  → event_state = "normal"
  → subject_normalized = "catchup on malaysia deployment"
  → fingerprint = "heineken.com|catchup on malaysia deployment|20260526"

✅ These produce DIFFERENT fingerprints — correct.
```

### Assign `dedup_status` per email:

| Condition | `dedup_status` |
|---|---|
| `existing_fps` provided AND `fp` found in set | `"seen"` |
| `existing_fps` provided AND `fp` NOT in set | `"new"` |
| `existing_fps` NOT provided (standalone mode) | `"unknown_standalone"` |

**Rules:**
- `"seen"` emails: include in `email_records` with all fields + `dedup_status`, but **skip** action/decision/risk bucket emission unless `force_reprocess=true`
- `"new"` emails: full processing, emit to all applicable buckets
- `"unknown_standalone"` emails: treat as candidate records, emit to all buckets, but caller must treat downstream output as unverified against Supabase

**Never read `[EMAILS]` from Mem0 for dedup.** Dedup source is Supabase only (via `existing_fps`).

---

## STEP C — CLASSIFY & TAG

For each email (regardless of `dedup_status`), assign **one primary tag** + optional **secondary tags**.  
Tags are metadata only — stored in output records, never written as separate cache entries.

### Primary Tag (pick the highest matching):

| Tag | Condition |
|---|---|
| `[URGENT]` | Subject/body contains: urgent, ASAP, blocker, prod down, P1, critical, hotfix |
| `[INCIDENT]` | Subject contains: incident, INC, outage, down, crash, 500, error in prod |
| `[DEPLOY]` | Subject contains: deploy, release, go-live, prod push, cutover, OMS live |
| `[APPROVAL]` | Subject contains: approve, approval, sign-off, sign off, confirm, review needed **OR body asks for Nghiem's input/decision before finalizing (see Action Detection Rule in STEP D)** |
| `[DECISION]` | Subject contains: decision, agreed, confirmed, alignment, direction, scope change |
| `[INFO]` | Default if none of the above match |

### Secondary Tags (append all that match):

| Tag | Condition |
|---|---|
| `[OPCO:MY]` | Malaysia / MY / MYS in subject or sender domain `heineken.com` + MY context |
| `[OPCO:ID]` | Indonesia / MBI / ID in subject |
| `[OPCO:KH]` | Cambodia / KH / Kinneth in sender |
| `[OPCO:LA]` | Laos / LA in subject |
| `[OPCO:TW]` | Taiwan / TW in subject |
| `[OPCO:IN]` | India / FieldAssist / UB India in subject or sender |
| `[MODULE:REP]` | REP, execution, outlet, route in subject |
| `[MODULE:LOOP]` | LOOP, delivery, POD, signature in subject |
| `[MODULE:HAP]` | HAP, CHUB, customer module in subject |
| `[MODULE:PEM]` | PEM, promo, promotion, claim in subject |
| `[MODULE:OMS]` | OMS, order, invoice, BBI in subject |
| `[CAPACITY]` | FTE, resource, capacity, SOW, cost, budget, headcount in subject |
| `[GOVERNANCE]` | Peter, YiLun, Andrea, PMO, governance, VN-GOV, full picture in subject/sender |

---

## STEP D — EXTRACT STRUCTURED RECORD (NormalizedSignal)

For each email with `dedup_status != "seen"` (or all if `force_reprocess=true`), run a **single LLM extraction pass** over the batch.  
Output must conform to the `NormalizedSignal` schema from `omni-config` section 16 + EMAIL_EXTRA_FIELDS.

### Extraction prompt:

```
For each email below, extract ONLY the specified fields as a JSON array.
Output must conform to NormalizedSignal schema (omni-config section 16).
CRITICAL: Do NOT include raw email body text anywhere in output.

For each email, produce:
{
  // NormalizedSignal base fields
  "signal_id":      "EMAIL-<YYYYMMDD>-<first4 of fp>",
  "source":         "EMAIL",
  "source_id":      "<Outlook message ID or internet_message_id>",
  "ts":             "<YYYY-MM-DD HH:MM GMT+7>",
  "actor":          "<sender display name>",
  "signal":         "<DECISION|BLOCKER|URGENT|DEPLOY|DIRECTION|INCIDENT|APPROVAL|INFO>",
  "summary":        "<≤25 words: ACTOR [verb] WHAT. Action: [next step] or none.>",
  "module":         "<REP|LOOP|HAP|PEM|OMS|CC|OMNI|null>",
  "opco":           "<MY|ID|KH|LA|TW|IN|MM|ALL|null>",
  "next_action":    "<specific action or null>",
  "owner":          "<Nghiem|team member|null>",
  "status":         "active",
  "confidence":     "<high|medium|low>",

  // EMAIL_EXTRA_FIELDS
  "fingerprint":    "<fingerprint: domain|subject_norm|YYYYMMDD>",
  "dedup_status":   "<new|seen|unknown_standalone>",
  "event_state":    "<canceled|updated|rescheduled|normal>",
  "from_email":     "<sender email address>",
  "to_type":        "<direct|cc>",
  "subject":        "<cleaned subject — no Re:/Fwd./[external]; retain Canceled:/Updated:/Rescheduled:>",
  "primary_tag":    "<URGENT|DEPLOY|DECISION|APPROVAL|INCIDENT|INFO>",
  "secondary_tags": ["<OPCO:XX>", "<MODULE:XX>"]
}

Signal/confidence rules — see omni-config section 16.

Summary — HARD constraints:
- Max 25 words total (including action clause)
- Format: "<Actor> [verb] <what>. Action: <action or none>."
- MUST include: specific names, OPCO codes, module names where present
- FORBIDDEN: vague phrases like "update on X", "email about Y"
- Action clause: MANDATORY — write "Action: none." if no action needed, never omit

ACTION DETECTION RULE — CRITICAL, apply before writing "Action: none.":
If the email body contains ANY of: "your thoughts/take/input", "let me know",
"before we finalize/proceed", "please confirm", meeting offer, or ends with "?" directed at Nghiem
→ next_action and Action clause MUST describe the specific reply needed
→ upgrade signal to APPROVAL if sender seeks sign-off before finalizing

Good examples:
  "Kezia assigned Phase1 Myanmar to Nghiem. Action: review subtasks in ticket."
  "Andrea confirmed 11.25 FTE plan, no changes needed. Action: none."
  "Tan Vu: KH image link expired in prod (INC6236715). Action: investigate ServiceNow ticket."
  "Thu asked for OMS order_id relocation feasibility before finalizing UI. Action: reply with feasibility assessment."

Bad examples (REJECT and re-extract):
  "Email about Malaysia project." → too vague
  "Thu looped Nghiem on OMS Order Table UI. Action: none." → WRONG — direct question present
```

**Summary enforcement**: if LLM returns summary > 25 words or matching a FORBIDDEN pattern, re-run extraction for that record only.  
**Action enforcement**: if LLM returns "Action: none." but email body contains any ACTION DETECTION RULE trigger phrase, re-extract that record.

---

## STEP E — CLASSIFY INTO OUTPUT BUCKETS

After extraction, route each record into output buckets.  
**No Mem0 write in this step.**

### Routing rules:

| Bucket | Criteria |
|---|---|
| `email_records` | **All** emails (NEW + SEEN + unknown_standalone) — always populated |
| `sent_records` | Emails from Nghiem's own address (outbound) — if returned by `outlook_email_search` |
| `action_records` | `dedup_status != "seen"` (or `force_reprocess=true`) AND `next_action != null` AND `owner == "Nghiem"` |
| `decision_records` | `dedup_status != "seen"` (or `force_reprocess=true`) AND `signal == "DECISION"` AND `confidence in [high, medium]` |
| `risk_records` | `dedup_status != "seen"` (or `force_reprocess=true`) AND `signal in [URGENT, INCIDENT, BLOCKER]` AND `confidence in [high, medium]` |

**Key rule**: `dedup_status = "seen"` emails appear in `email_records` only. They do NOT emit to action/decision/risk buckets unless `force_reprocess=true`.

### `email_records` and `sent_records` item shape (full NormalizedSignal + dedup fields):
```json
{
  "signal_id": "...",
  "source": "EMAIL",
  "source_id": "...",
  "ts": "...",
  "actor": "...",
  "signal": "...",
  "summary": "...",
  "module": "...",
  "opco": "...",
  "next_action": "...",
  "owner": "...",
  "status": "active",
  "confidence": "...",
  "fingerprint": "...",
  "dedup_status": "new|seen|unknown_standalone",
  "from_email": "...",
  "to_type": "...",
  "subject": "...",
  "primary_tag": "...",
  "secondary_tags": [...]
}
```

### `action_records` item shape:
```json
{
  "signal_id": "...",
  "source": "EMAIL",
  "source_id": "...",
  "fingerprint": "...",
  "dedup_status": "new|unknown_standalone",
  "actor": "...",
  "summary": "...",
  "next_action": "...",
  "owner": "Nghiem",
  "module": "...",
  "opco": "...",
  "due": null,
  "status": "open",
  "confidence": "...",
  "ts": "..."
}
```

### `decision_records` item shape:
```json
{
  "signal_id": "...",
  "source": "EMAIL",
  "source_id": "...",
  "fingerprint": "...",
  "dedup_status": "new|unknown_standalone",
  "actor": "...",
  "summary": "...",
  "module": "...",
  "opco": "...",
  "confidence": "...",
  "ts": "...",
  "status": "confirmed"
}
```

### `risk_records` item shape:
```json
{
  "signal_id": "...",
  "source": "EMAIL",
  "source_id": "...",
  "fingerprint": "...",
  "dedup_status": "new|unknown_standalone",
  "actor": "...",
  "summary": "...",
  "module": "...",
  "opco": "...",
  "severity": "critical|high",
  "confidence": "...",
  "ts": "...",
  "status": "open"
}
```

Severity mapping: `URGENT/INCIDENT` → `critical`, `BLOCKER` → `high`.

---

## STEP F — OPTIONAL DURABLE-FACT WRITES (Supabase only)

⛔ Mem0 is retired. Durable long-term facts go to the appropriate Supabase table.
Write **only** if the email contains a confirmed, durable fact of one of these types:

| Fact type | Supabase target | Trigger condition |
|---|---|---|
| Recurring pattern | `upsert_knowledge_fact('intel_pattern', '<pattern_slug>', {...})` | Repeated behavior observable across 3+ emails from same sender/context |
| Comm style update | `upsert_user_preference('comm_style_global', 'nghiem:global', {...})` | Nghiem's own sent email reveals a new/updated communication style pattern |
| Structural risk | `upsert_risks()` (risk_key: `<module>:<market>:<risk_slug>`) | Structural risk spanning >1 sync window (not transient/single-incident) |
| Governance decision | `upsert_decisions()` (decision_key: `email:<date>:<slug>`) | Governance decision confirmed at leadership level |
| Stakeholder fact | `upsert_user_preference('stakeholder_profile', 'nghiem:{Name}', {...})` | Role change, new contact, or preference that should persist |

**Only the five targets above.** Do not invent new fact_types.

**BLOCKED — never write anywhere:**
- Raw email lists / sync snapshots as knowledge_facts ← belongs in `source_items` (caller handles)
- Pipe-delimited flat-text cache ← blocked
- Transient single-email observations ← not durable, skip

If no durable facts qualify → skip STEP F entirely. **Zero STEP F writes is correct behavior for most runs.**

---

## STEP G — RETURN RESULT TO CALLER

Return the following contract to `omni-data-sync` STEP 2:

```python
{
  # Structured records for Supabase upsert (caller handles upsert)
  "email_records":    [...],   # ALL emails (new + seen + unknown_standalone), full NormalizedSignal + dedup fields
  "sent_records":     [...],   # outbound emails (may be empty)
  "action_records":   [...],   # new/unknown emails requiring Nghiem's action
  "decision_records": [...],   # confirmed decisions (new/unknown only)
  "risk_records":     [...],   # urgent/incident/blocker signals (new/unknown only)

  # Metadata
  "emails_total":     N,
  "emails_new":       N,
  "emails_seen":      N,
  "emails_unknown":   N,       # count of unknown_standalone
  "flagged_urgent":   N,       # count where primary=[URGENT] or [INCIDENT]
  "cap_warning":      true/false,
  "durable_facts_written": N,      # count of STEP F Supabase durable-fact writes (0 most runs)
  "standalone_mode":  true/false   # true if existing_fps was not provided
}
```

If running **standalone**, also print summary to chat:
```
EMAIL EXTRACTION — <datetime> GMT+7
  Mode: STANDALONE (dedup_status = unknown_standalone for all records)
  Fetched: N emails | New: N | Seen: N | Unknown: N
  Tags: URGENT=X | DEPLOY=X | INCIDENT=X | APPROVAL=X | DECISION=X | INFO=X
  OPCOs: MY=X | ID=X | IN=X | ...
  Buckets: actions=X | decisions=X | risks=X
  Durable facts written (STEP F): X (or none)
  ⚠️ No email-list cache written anywhere. Records returned for Supabase source_items upsert only.
  ⚠️ Standalone mode: dedup not verified against Supabase. Caller should deduplicate before upsert.
```

---

## GUARDRAILS

**Write restrictions (absolute):**
- ⛔ Any Mem0 call → **BLOCKED. Mem0 is retired — any code path calling Mem0 is a regression.**
- Email-list / sync-snapshot cache blobs in knowledge_facts → **BLOCKED.** (source_items is the only email store; caller upserts.)
- Pipe-delimited flat-text cache → **BLOCKED.**
- Reading any legacy Mem0 cache for dedup → **BLOCKED.** Dedup uses `existing_fps` from caller only.

**Dedup rules:**
- Production: `existing_fps` MUST be passed by omni-data-sync from Supabase `source_items`
- Standalone: no `existing_fps` → all records get `dedup_status = "unknown_standalone"`
- `dedup_status = "seen"` → emit to `email_records` only; never emit to action/decision/risk buckets unless `force_reprocess=true`

**Fingerprint rules:**
- Every item in `email_records` and `sent_records` MUST carry `fingerprint`, `dedup_status`, and `event_state` fields
- Subject normalization: strip `re:`, `fw:`, `fwd:`, `[external]` only — **never strip** `canceled:`, `cancelled:`, `updated:`, `rescheduled:`
- `event_state` must be derived from subject prefix BEFORE normalization; default = `"normal"`
- Missing fingerprint or `event_state` on any output record = bug; do not emit incomplete records

**Extraction quality rules:**
- Single batch LLM call for all records — not one call per email
- Re-extract individual records that fail summary or action enforcement; do not silently store bad output
- No raw email body text in any output field or stored fact — summary is the only payload

**Error handling:**
- If bucket build fails → log error, return partial result with `error` field; do not abort caller flow
- If a STEP F durable-fact write fails → log, decrement `durable_facts_written`, continue; do not abort
- Empty fetch result → return empty buckets + metadata; do not skip return

---

## CHANGELOG

| Version | Change |
|---|---|
| v4.0 | **Supabase-only (Mem0 retired).** STEP F rewritten: durable facts → knowledge_facts/user_preferences/risks/decisions via omni-utils helpers. Return contract: `mem0_written` → `durable_facts_written`. All Mem0 read/write paths removed. |
| v3.0 | **Phase 2B Supabase migration + fingerprint patch.** Old STEP E (Mem0 `[EMAILS]` write) removed entirely. New STEP B: dedup uses `existing_fps` from caller (Supabase) — never reads Mem0; introduces `dedup_status` field (`new`/`seen`/`unknown_standalone`); fingerprint normalization patched — event-state prefixes (`Canceled:`, `Updated:`, `Rescheduled:`) preserved in fingerprint to distinguish invite states; `event_state` field added to EMAIL_EXTRA_FIELDS. New STEP E: bucket classification with explicit routing rules; `dedup_status=seen` emails blocked from action/decision/risk buckets unless `force_reprocess=true`. New STEP F: narrow atomic Mem0 write rules — only `[PATTERN]`, `[COMM-STYLE]`, `[RISK]`, `[DECISION]`, `[STAKEHOLDER]` allowed; no new tags. STEP G return contract expanded to `email_records`, `sent_records`, `action_records`, `decision_records`, `risk_records` + `emails_unknown`, `standalone_mode` metadata fields. |
| v2.3 | NormalizedSignal schema. `actor`, `signal`, `next_action`, `signal_id` fields added. |
| v2.2 | `source_id` (Outlook message ID) added to schema and output. |
| v2.1 | ACTION DETECTION RULE added. `[APPROVAL]` upgrade logic. Action enforcement guardrail. |
| v2.0 | Single batch LLM call. 25-word summary cap. `action` folded into summary. |
| v1.0 | Initial version. |
