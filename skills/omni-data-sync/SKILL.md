---
name: omni-data-sync
description: "Centralized data fetch for OMNI program (Supabase-only; Mem0 retired). v12.9: STEP 5-EXP CALENDAR AUTO-EXPIRY — archives calendar-prep actions 2+ days past meeting (open/needs_review only, reversible, fail-open); DB TAXONOMY CONTRACT — canonical source (15 values) + priority P0–P3 enforced by DB CHECK constraints + normalize trigger (migration 2026-07-02); 'archived' is terminal, open-pool queries whitelist active statuses. v12.8: STEP 7A-WI AUTO-FILL APPROVAL INBOX — idempotent generate_work_items() refills inbox; surface-only, governance guards in DB. v12.7: STEP 7A0-B dense response-outcome ledger (acted/ignored/overridden) for omni-operator-learning. v12.6: STEP 2C sent-reconciliation auto-closes replied actions. STEP 4F: ClickUp comments mandatory in FULL/LIGHTWEIGHT. Requires omni-utils v11.2 + omni-config v1.5. Triggers: 'sync data', 'refresh data', 'fetch latest', 'run data sync', 'update memory from sources', or when cache stale."
---

# OMNI Centralized Data Sync

You are running the OMNI centralized data fetch for Nghiem Tan Nguyen.
Goal: pull all source data ONCE, write structured memory, so downstream skills skip redundant API calls.

---

## ⚠️ READ FIRST — SHARED CONFIG + UTILS

**Before executing any step, read in this order:**
1. `/mnt/skills/user/omni-config/SKILL.md` → loads constants (CONFIG_VERSION = "1.8")
2. `/mnt/skills/user/omni-utils/SKILL.md` → loads utilities (UTILITY_VERSION = "11.2")

## ⛔ MEM0 IS RETIRED — v12.0

```
Mem0 skipped — Supabase is now the source of truth.
```

Do NOT call any Mem0 function in this skill. There is no Mem0 fallback.
If Supabase is unavailable → `write_action()` and all upsert helpers print fallback SQL for manual insert.

**Utilities available from omni-utils v11.1:**

**Sync lifecycle:**
- `create_sync_run()` — opens a sync run record in Supabase, returns `sync_id`
- `complete_sync_run()` — closes the run with status + sources summary
- `get_latest_sync_run()` — reads most recent sync_run row for window calculation

**Source data upserts:**
- `upsert_source_items()` — batch upsert; conflict key = `(source_type, external_id)`
- `make_comment_external_id()` — stable dedup key for ClickUp comments
- `upsert_actions()` — batch upsert; conflict key = `action_key`
- `upsert_decisions()` — batch upsert; conflict key = `decision_key`; status enum: confirmed/proposed/pending/unclear/rejected
- `upsert_risks()` — batch upsert; conflict key = `risk_key`

**Context and cache:**
- `upsert_context_pack()` — store pre-built context pack
- `build_context_pack_from_supabase()` — build structured context from Supabase tables
- `cache_check()` — Supabase-only freshness check; returns degraded=True if unavailable
- `cache_check_from_supabase()` — direct Supabase sync_runs freshness check
- `get_context_pack()` — Supabase-only context pack; returns degraded=True if unavailable

**Long-term knowledge (durable facts only — do NOT use for transient sync data):**
- `upsert_knowledge_fact()` — for durable [INTEL][*] facts, patterns — written by omni-eod-review and omni-sent-analyzer only
- `upsert_user_preference()` — for comm style and stakeholder profiles — written by omni-sent-analyzer only
- `upsert_project_context()` — for project reference docs — written by project-knowledge-sync only

**Action log:**
- `write_action()` — writes skill completion log to Supabase `actions` table (v11.0: Mem0 retired)

**Maintenance:**
- `cleanup_old_raw_items()` — rolling retention delete for source_items
- `cleanup_stale_knowledge_facts()` — deletes expired knowledge_facts rows
- `run_duplicate_audit()` — post-sync duplicate check; call in STEP 8

**UTILITY_VERSION = "11.2"**

### ⚠️ external_id rules (mandatory)

Every item passed to `upsert_source_items()` MUST have `external_id` set correctly.
Duplicate prevention depends entirely on this field.

| source_type | external_id value |
|---|---|
| `clickup_task` | ClickUp task ID — e.g. `'86exkz2rt'` |
| `clickup_comment` | `make_comment_external_id(comment_id, task_id, created_at, author, text)` |
| `email` | Graph message ID or internet-message-id |
| `teams_message` | Teams message ID |
| `calendar_event` | Graph event ID |
| `ado_work_item` | ADO work item ID as string |

---

## SUPABASE WRITE FLOW (every run)
```
STEP 0  → cache_check()                    → read sync_runs freshness
STEP 0A → create_sync_run()                → opens sync_id, status=running
STEP 2  → upsert_source_items(email)       → inbound emails
STEP 2B → upsert_source_items(sent_email)  → sent emails
STEP 2C → reconcile_sent_vs_open_actions() → auto-close replied reply/follow-up actions
STEP 3  → upsert_source_items(teams_message) → Teams signals
STEP 4  → upsert_source_items(clickup_task)  → ClickUp tasks
STEP 4F → upsert_source_items(clickup_comment) → comment signals
STEP 4F → upsert_actions()                 → reply-needed + ACTION signals
STEP 4F → upsert_decisions()               → DECISION signals from comments
STEP 4F → upsert_risks()                   → RISK/BLOCKER signals from comments
STEP 5  → upsert_source_items(calendar_event) → calendar events
STEP 5-EXP → auto-archive expired calendar-prep actions (2+ days past)  ⭐ v12.9
STEP 6  → resolve_feature_key() + rollup_feature_status() → feature_status  ⭐ v12.2
        → auto-supersede satisfied actions (confidence-gated)
STEP 7  → build_context_pack_from_supabase()   (includes feature_rollup)
        → upsert_context_pack("briefing")
STEP 7A-WI → generate_work_items()             → refill Approval Inbox (idempotent, surface-only)  ⭐ v12.8
        → complete_sync_run()
STEP 7B → cleanup_old_raw_items()          → rolling retention
```

### ⛔ DB TAXONOMY CONTRACT ⭐ v12.9 (migration 2026-07-02, non-negotiable)

The `actions` table now enforces canonical values at the DB layer — CHECK constraints plus a
`BEFORE INSERT/UPDATE` normalization trigger:

- **`source`** — 15 canonical values only. External: `email`, `sent_email`, `teams_message`,
  `clickup_task`, `clickup_comment`, `ado_work_item`, `calendar_event`. Internal: `sync`,
  `briefing`, `eod`, `learning`, `self_improve`, `requirement_analyzer`, `ado_sync`, `operator`.
  Legacy variants (`EMAIL`, `TEAMS`, `calendar`, skill names…) are auto-mapped by the trigger —
  write canonical values anyway; the trigger is a safety net, not a license.
- **`priority`** — `P0`–`P3` only. `urgent`→P0, `high/1/p1`→P1, `2/normal/p2`→P2, `3/low`→P3.
- **`status`** — allowed: `open`, `in_progress`, `done`, `blocked`, `superseded`,
  `needs_review`, `archived`. **`archived` and `superseded` are TERMINAL** — every open-pool
  query MUST whitelist active statuses (`status IN ('open','in_progress',...)`), never
  blacklist `done` alone.

### feature_key at write-time (v12.2)

Every item built in STEPs 2, 2B, 3, 4, 4F SHOULD include `feature_key` resolved via
`resolve_feature_key(item, registry)` (load registry once at STEP 0B, after sync run opens).
This is best-effort at write-time — STEP 6B catches any rows left NULL. Calendar events
(STEP 5) are tagged only when title clearly references a feature.

### Dedup key conventions:
```python
# action_key:  "<source_type>:<item_id>:<action_slug>"
# e.g. "clickup_comment:cu-abc123:reply-blocker"
#      "email:MSG456:follow-up-kezia"
#      "teams_message:MSG789:confirm-decision"

# decision_key: "<source_type>:<YYYY-MM-DD>:<decision_slug>"
# e.g. "teams_message:2026-05-25:hap-mm-acc-deploy"
#      "email:2026-05-25:loop-my-scope-confirmed"

# risk_key: "<module>:<market>:<risk_slug>"
# e.g. "hap:mm:uat-overdue"
#      "loop:my:qa-blocked"
#      "oms:id:deploy-dependency"
```

All function implementations live in `omni-utils`. Do NOT copy them here.
Reference this skill's utilities by reading that file, then use inline.

---

## STEP 0 — CHECK STALENESS + OPEN SYNC RUN

### STEP 0A — Cache check (Supabase-only)

Call `cache_check()` from omni-utils v11.1. This reads from `sync_runs` table in Supabase only.
There is no Mem0 fallback. If Supabase is unavailable, `cache_check()` returns `degraded=True, mode="LIVE"`.

```python
cache = cache_check(stale_threshold_h=2)
# cache["hit_type"] = "supabase_sync_run"           → Supabase OK
# cache["hit_type"] = "supabase_cache_check_missing" → first run, no records yet
# cache["hit_type"] = "supabase_unavailable"         → Supabase down, degraded=True → force FULL mode
```

- `cache["mode"] == "CACHE"` AND triggered by another skill (not manual) → **LIGHTWEIGHT MODE**
  (Steps 2 + 2B only; skip Teams, ClickUp live fetch, Calendar; run STEP 4F in `clickup_comments_light` mode; then STEP 6 FEATURE ROLLUP; then STEP 7)
  Add to header: `(cache — synced <cache["summary"]>)`
- `cache["mode"] == "CACHE"` AND manual trigger → **FULL MODE**
- `cache["mode"] == "WARN"` → **FULL MODE** + add gap warning
- `cache["mode"] == "LIVE"` → **FULL MODE**
- `cache["age_hours"] > 72` → **FULL MODE** + add `⚠️ Gap >72h detected` warning

⚠️ **FULL MODE EXECUTION RULE — NON-NEGOTIABLE**: In FULL mode, STEP 4 (ClickUp fetch) MUST always execute a live API call. In FULL mode, ClickUp cache age is IRRELEVANT — always fetch live. Never skip STEP 4 in FULL mode for any reason.

### STEP 0B — Open sync run in Supabase

**Call immediately after determining sync mode. Required every run.**

```python
# Determine sync_type
sync_type = current_sync_mode  # "FULL" | "LIGHTWEIGHT" | "DEEP" | "CACHE_ONLY"

# Open sync run — returns sync_id UUID
sync_id = create_sync_run(
    sync_type    = sync_type,
    window_start = None,          # will be updated after STEP 1 calculates it
    window_end   = None,          # will be updated at STEP 7 completion
    sources_ok   = [],
    sources_failed = [],
    summary      = f"sync started — mode:{sync_type}",
)

if not sync_id:
    print("⚠️ WARNING: create_sync_run() failed — continuing without sync_id. Supabase writes will use NULL sync_id.")
    # Never abort the sync for this — log and continue
    sync_id = None

print(f"[STEP 0B] supabase_sync_run_created: id={sync_id} type={sync_type}")

# Carry sync_id forward — passed to all upsert calls in STEPS 2–5
# sources_ok and sources_failed lists are built throughout the run:
sources_ok     = []   # populated as each source succeeds
sources_failed = []   # populated as each source errors
```

---

## STEP 1 — DETERMINE TIME WINDOW

1. Get current time GMT+7 via `user_time_v0`.
2. Read last run timestamp: call `get_latest_sync_run()` → read `run_at` field.
   - If no Supabase record (first run) → use 18h default window.
   - Do NOT fall back to Mem0 `[DATA-SYNC]` — Mem0 is retired.
3. Calculate gap = current time − last run timestamp.

**Window logic:**
| Condition | Window start | Label |
|---|---|---|
| Last run found AND gap ≤ 72h | Use last run timestamp exactly | `since <YYYY-MM-DD HH:MM>` |
| Last run found AND gap > 72h | Current time − 72h (cap) | `72h cap (last sync was X days ago)` |
| No last run record | Current time − 18h | `18h default (first run)` |

- **Never use hardcoded 8h/18h** when a last-run timestamp exists.
- Store `window_start` (ISO datetime) and `window_label` for all fetch steps.
- If gap > 72h: add warning — `⚠️ Gap >72h detected. Fetched last 72h only. Older data not retrieved.`

```python
# After calculating window_start, update the sync_run record
if sync_id:
    complete_sync_run(
        sync_id      = sync_id,
        status       = "running",   # still running — just updating window fields
        sources_ok   = [],
        sources_failed = [],
        summary      = f"window: {window_label}",
    )
    # Note: complete_sync_run with status="running" is a partial update — acceptable
    # Full completion happens at STEP 7
```

---

## STEP 2 — FETCH EMAILS (Outlook)

**Delegated to skill: `omni-email-extractor`** — read `/mnt/skills/user/omni-email-extractor/SKILL.md` and execute it fully.

Pass the following inputs:
- `window_start` — from STEP 1
- `window_label` — from STEP 1
- `current_time` — from STEP 1

The skill handles: fetching, noise filtering, fingerprint deduplication, rich tag classification
(`[URGENT]`, `[DEPLOY]`, `[INCIDENT]`, `[APPROVAL]`, `[DECISION]`, `[INFO]` + secondary
`[OPCO:XX]`, `[MODULE:XX]`, `[CAPACITY]`, `[GOVERNANCE]`).

⚠️ **v11.0 CHANGE**: `omni-email-extractor` must return structured email records for Supabase upsert.
Do NOT write `[EMAILS]` to Mem0 — that tag is blocked. Instead, collect email records and upsert here.

Receive the result dict:
- `emails_total` → total fetched
- `emails_new` → after dedup
- `flagged_urgent` → count where primary = `[URGENT]` or `[INCIDENT]`
- `email_records` → list of structured dicts (one per email, see field mapping below)
- `cap_warning` → true/false (log ⚠️ if true)

**After receiving email_records, upsert to Supabase:**

```python
# Map each email record to source_items schema
email_items = []
for email in email_records:
    email_items.append({
        "source_type":      "email",
        "item_id":          email.get("message_id") or email.get("id"),
        "title":            email.get("subject", "")[:500],
        "summary":          email.get("summary", "")[:1000],  # AI-extracted summary, not body
        "body_excerpt":     email.get("body_excerpt", "")[:500],  # first 500 chars only
        "source_url":       email.get("web_link") or email.get("url"),
        "sender":           email.get("sender") or email.get("from"),
        "tags":             email.get("tags", []),            # [URGENT], [DEPLOY], [OPCO:MY], etc.
        "market":           email.get("opco"),                # MY, ID, KH, etc.
        "module":           email.get("module"),              # REP, LOOP, HAP, etc.
        "priority":         "P1" if email.get("primary_tag") in ["URGENT","INCIDENT"] else "P2",
        "status":           "unread",
        "is_urgent":        email.get("primary_tag") in ["URGENT", "INCIDENT"],
        "is_client_facing": email.get("is_client_facing", False),
        "item_created_at":  email.get("received_at"),
        "item_updated_at":  email.get("received_at"),
    })

if email_items:
    upsert_source_items(sync_id=sync_id, items=email_items)
    sources_ok.append("email")
    print(f"[STEP 2] supabase_source_items_upserted: type=email count={len(email_items)}")
else:
    print("[STEP 2] No new emails to upsert")
    sources_ok.append("email")  # still counts as ok — just no new records
```

**LIGHTWEIGHT MODE: run the skill in lightweight pass (inbox emails only) → proceed to STEP 2B → then STEP 4F in `clickup_comments_light` mode → then STEP 6 FEATURE ROLLUP → STEP 7.**

---

## STEP 2B — ANALYZE SENT EMAILS

**Delegated to skill: `omni-sent-analyzer`** — read `/mnt/skills/user/omni-sent-analyzer/SKILL.md` and execute it.

Determine sent analysis mode from current sync mode:
- LIGHTWEIGHT or FULL → `mode = "DAILY"`
- DEEP → `mode = "HISTORICAL"`

```python
sent_mode = "HISTORICAL" if current_sync_mode == "DEEP" else "DAILY"

sent_result = run_omni_sent_analyzer(
    mode         = sent_mode,
    window_start = window_start,   # ISO datetime — used in DAILY mode only
)
```

Receive result dict for STEP 8 summary:
- `emails_analyzed` → sent emails processed
- `commitments_found` → count
- `decisions_found` → count
- `follow_ups_found` → count
- `profiles_updated` → list of stakeholder profile names updated
- `sent_records` → list of structured dicts for Supabase upsert (v11.0 new field)

**After receiving sent_records, upsert to Supabase:**

```python
sent_items = []
for sent in (sent_result.get("sent_records") or []):
    sent_items.append({
        "source_type":      "sent_email",
        "item_id":          sent.get("message_id") or sent.get("id"),
        "title":            sent.get("subject", "")[:500],
        "summary":          sent.get("summary", "")[:1000],
        "source_url":       sent.get("web_link"),
        "sender":           "Nghiem",   # always Nghiem for sent
        "tags":             sent.get("tags", []),
        "market":           sent.get("opco"),
        "module":           sent.get("module"),
        "is_client_facing": sent.get("is_client_facing", False),
        "item_created_at":  sent.get("sent_at"),
        "item_updated_at":  sent.get("sent_at"),
    })

# Upsert decisions found in sent emails
sent_decisions = []
for d in (sent_result.get("decision_records") or []):
    decision_date = d.get("date", run_date)
    slug = d.get("topic", "decision").lower().replace(" ", "-")[:30]
    sent_decisions.append({
        "decision_key":   f"sent_email:{decision_date}:{slug}",
        "decision_date":  decision_date,
        "description":    d.get("description", ""),
        "topic":          d.get("topic"),
        "module":         d.get("module"),
        "market":         d.get("market"),
        "source":         "sent_email",
        "made_by":        "Nghiem",
        "status":         "confirmed",
    })

if sent_items:
    upsert_source_items(sync_id=sync_id, items=sent_items)
    sources_ok.append("sent_email")
    print(f"[STEP 2B] supabase_source_items_upserted: type=sent_email count={len(sent_items)}")

if sent_decisions:
    upsert_decisions(sync_id=sync_id, decisions_list=sent_decisions)
    print(f"[STEP 2B] supabase_decisions_upserted: count={len(sent_decisions)}")

# omni-sent-analyzer v2.0+ writes comm style and stakeholder profiles to
# Supabase user_preferences and knowledge_facts — NOT to Mem0.
# This skill does not need to handle those writes — they are internal to omni-sent-analyzer.
```

**CACHE MODE**: skip entirely (cache still fresh).
**LIGHTWEIGHT**: DAILY mode — sent window matching inbox window_start, fast.
**FULL**: DAILY mode — same window as inbox.
**DEEP**: HISTORICAL mode — 3-month batch scan.

⚠️ If `omni-sent-analyzer` fails → log in `sources_failed` as `"SENT-ANALYZER"`, continue. Do NOT abort sync.

### ⛔ MANDATORY ENFORCEMENT — SENT MAIL (NON-NEGOTIABLE)

**STEP 2B MUST execute in every FULL and LIGHTWEIGHT run. It is NOT optional.**

Sent mail is operationally equivalent to inbox mail — skipping it means missed commitments, decisions, and follow-ups made by Nghiem since last sync.

**Forbidden skip reasons** (these are NOT valid justifications):
- "Sent analyzer was run recently" → irrelevant — always run for the current window
- "No new emails in inbox" → irrelevant — sent and inbox are independent sources
- "Saving tokens/time" → never a valid reason to skip a mandatory step

**Enforcement rule:**
```python
# FULL or LIGHTWEIGHT mode — NO EXCEPTIONS
assert current_sync_mode in ("FULL", "LIGHTWEIGHT", "DEEP"), "unexpected mode"
if current_sync_mode != "CACHE":
    # STEP 2B MUST run. If you are about to skip it, STOP — you are violating this rule.
    sent_result = run_omni_sent_analyzer(mode=sent_mode, window_start=window_start)
    if not sent_result.get("sent_records") and not sent_result.get("emails_analyzed"):
        log_warning("SENT-ANALYZER returned no records — logged in sources_failed, continuing")
```

**Window alignment**: sent `window_start` MUST match inbox `window_start` from STEP 1.

---

## STEP 2C — SENT-VS-OPEN-ACTIONS RECONCILIATION (mandatory, every FULL/LIGHTWEIGHT run)

**Purpose:** close the loop that caused stale `reply-needed`/`follow-up` carryovers — an action
opened from an inbound ask that Nghiem has *already answered* in Sent Items, but which the sync
never reconciled because its sent-fetch only covered the short sync window.

### ⚠️ Root-cause guard (the bug this fixes)
The STEP 2 / 2B sent fetch is **window-scoped**. A reply sent *before* this run's window but
*after* the action was created is invisible to it. So STEP 2C MUST do its **own** sent fetch
that looks back to the **oldest open reply-action's date**, NOT the sync window.

### 2C-1 — Load open reply/follow-up actions
```sql
SELECT action_key, title, source, source_ref, source_url, market, module,
       created_at::text, raw_json
FROM actions
WHERE status IN ('open','in_progress')
  AND source IN ('email','sent_email')
  AND (action_key ILIKE '%reply%' OR action_key ILIKE '%follow%'
       OR title ILIKE '%repl%' OR title ILIKE '%follow up%')
ORDER BY created_at ASC;          -- oldest first → oldest is the lookback floor
```
If none → log `[STEP 2C] no_open_reply_actions` and skip to STEP 3.

### 2C-2 — Lookback-scoped sent fetch
`lookback_floor = min(created_at over the rows above) − 1 day` (NOT the sync window_start).
Fetch Sent Items with `outlook_email_search(folderName='Sent Items', afterDateTime=lookback_floor,
order='newest', limit=25)`; paginate (`nextOffset`/`nextCursor`) until sent dates pass the floor
or 4 pages. Skip rows whose subject is a standup/scrum/cancelled invite.

### 2C-3 — Match + auto-close
For each open reply/follow-up action, find a sent mail that satisfies BOTH:
- **thread match:** same `conversationId` as the source email, OR subject matches after
  stripping `Re:|Fw:|Fwd:` prefixes, OR (recipient ∈ action stakeholders AND subject token-set
  overlap ≥ 0.6); AND
- **recency:** `sent_at > inbound_ask_at` (the source item / action creation time).

On a confident match (thread match true), write-back BEFORE the context pack is built:
```sql
UPDATE actions
SET status='done', updated_at=now(),
    title = title || ' [auto-closed STEP2C <run_date>: replied via sent mail <sent_msgid>]'
WHERE action_key = :action_key AND status IN ('open','in_progress');
-- if the action links a clickup_comment, also clear its source row:
UPDATE source_items SET reply_status='replied', synced_at=now()
WHERE source_type='clickup_comment' AND external_id = :linked_comment_id;
```
Low-confidence match (only subject/recipient heuristic, no conversationId) → do **NOT** auto-close;
set `status='needs_review'` and append `raw_json.reconcile_hint='possible sent reply <msgid>'`.

### 2C-4 — Guards (non-negotiable)
- **Fail-open:** any error in 2C is logged and skipped — never abort the sync.
- **Idempotent:** re-running closes nothing already `done`.
- **Never auto-close** governance/capacity/SOW actions on a heuristic match — those require an
  explicit thread (`conversationId`) match; otherwise → `needs_review`.
- **Never** touch `clickup_task`/ADO/calendar-prep actions here (out of scope — STEP 6 / self-improve own those).
- Count closures + needs_review into STEP 8 summary as `sent_reconciled:N | reconcile_review:N`.

---

## STEP 3 — FETCH TEAMS MESSAGES

⚠️ **CRITICAL: Teams search API quirk** — `chat_message_search` ONLY returns results for very broad
single-word queries. Specific keywords, sender names, or group names all return empty. Always use
broad queries first. Never rely solely on keyword filtering.

### 3A — Broad keyword search (always run)
Run `chat_message_search` with query `"OMNI"` within the time window (limit: 50).
This is the primary sweep — catches most relevant messages across all chats.

### 3B — Monitor known group chats directly (always run)
For each chat below, fetch the latest messages using `read_resource` with the chat URI.
Do NOT rely on search to find these — read them directly every run:

| Chat | ChatId | URI |
|---|---|---|
| VN-OMNI Governance | 19:d9f895cfc1794e678a6d289a1392e992@thread.v2 | `teams:///chats/19%3Ad9f895cfc1794e678a6d289a1392e992%40thread.v2/messages` |
| Nghiem ↔ Huy Phan | 19:8e31c820-093c-4254-836d-6938399ea304_d3c599a6-fc79-4a2e-b9d0-0c9495d666b4@unq.gbl.spaces | `teams:///chats/19%3A8e31c820-093c-4254-836d-6938399ea304_d3c599a6-fc79-4a2e-b9d0-0c9495d666b4%40unq.gbl.spaces/messages` |

If `read_resource` returns 502/error for a chat, log it in summary with tag `sources_failed: ["TEAMS-VN-GOV"]` or `["TEAMS-HuyPhan"]` and continue — do not abort.

⚠️ **partial sync tracking**: If any Teams fetch fails, record the failed source in the SYNC-META entry:
```
sources_failed: <comma-separated list, or "none">
```
Consumer skills reading `get_context_pack()` will see `sources_failed` populated and can warn accordingly.

### 3C — Flagging criteria
Flag messages from both 3A and 3B if they match ANY of:

**People (flag regardless of content):**
- Andrea, Yilun, Angelia, Kay Sheng, Kezia, Peter, Ha Hoang, Huy Phan

**Ops/tech keywords (English):**
- OMNI, REP, LOOP, HAP, deployment, bug, urgent, blocked, prod, incident

**Finance/capacity keywords (English):**
- PEM, budget, FTE, capacity, absorb, burst, cost, contract, invoice, scope, quote, SOW, estimate

**Vietnamese keywords (translate + flag — DO NOT skip):**
- "khách" (client/customer issue), "nhạy cảm" (sensitive), "align", "full picture",
  "estimate", "communicate", "deploy", "ticket", "SOW", "FTE", "ADO", "JIRA",
  "anh/chị" + action verb (senior giving direction), "Peter", "YiLun", "Andrea",
  "scale down", "resource", "capacity", "deadline"

⚠️ **Vietnamese rule**: Messages in Vietnamese carry the same weight as English. Always translate
and summarize Vietnamese content. The VN-OMNI Governance chat is primarily in Vietnamese.

### 3D — Structured extraction (single batch LLM call) → NormalizedSignal

After collecting all flagged messages, run **one LLM extraction call** for the full batch.
Do NOT process messages one by one.
Output must conform to the `NormalizedSignal` schema from `omni-config` section 16 + TEAMS_EXTRA_FIELDS.

#### Signal type classification (from omni-config SIGNAL_RULES):

| Signal | Condition |
|---|---|
| `DECISION` | Direction given, alignment confirmed, scope agreed, approval granted |
| `BLOCKER` | Work stopped, waiting on someone, prod issue, unresolved dependency |
| `URGENT` | Explicit urgency, deadline today/tomorrow, escalation, P1 mention |
| `DEPLOY` | Release, go-live, prod push, cutover, environment promotion |
| `DIRECTION` | Senior stakeholder (Andrea/Peter/YiLun/Kezia/KaySheng) giving instructions |
| `INCIDENT` | Production incident, data issue, system down |
| `INFO` | Default — relevant but no immediate action |

#### Extraction prompt:

```
For each Teams message below, extract ONLY the specified fields as a JSON array.
Output must conform to NormalizedSignal schema (omni-config section 16).
CRITICAL: Do NOT include raw message body text anywhere in output.
CRITICAL: If the message is in Vietnamese, translate — output in English only.

For each message, produce:
{
  // NormalizedSignal base fields
  "signal_id":   "TEAMS-<YYYYMMDD>-<first4 of sender+ts hash>",
  "source":      "TEAMS",
  "source_id":   "<Teams message ID if available, else 'unknown'>",
  "ts":          "<YYYY-MM-DD HH:MM GMT+7>",
  "actor":       "<sender display name>",
  "signal":      "<DECISION|BLOCKER|URGENT|DEPLOY|DIRECTION|INCIDENT|INFO>",
  "summary":     "<≤20 words: ACTOR [verb] WHAT. Action: [next step] or none.>",
  "module":      "<REP|LOOP|HAP|PEM|OMS|CC|OMNI|null>",
  "opco":        "<MY|ID|KH|LA|TW|IN|MM|ALL|null>",
  "next_action": "<specific action or null>",
  "owner":       "<Nghiem|team member|null>",
  "status":      "active",
  "confidence":  "<high|medium|low>",

  // TEAMS_EXTRA_FIELDS
  "chat":        "<VN-OMNI-GOV|Nghiem-HuyPhan|Direct|GroupName>",
  "translated":  "<true|false>"
}

Confidence rules — see omni-config section 16.

Summary — HARD constraints:
- Max 20 words total (including action clause)
- Format: "<Actor> [verb: said/confirmed/asked/reported/flagged/escalated] <what>. Action: <step or none>."
- MUST be in English — translate Vietnamese content
- MUST include specific names, OPCO codes, module names where present
- FORBIDDEN: vague phrases like "discussed project", "update on work", "mentioned something"
- Action clause: MANDATORY — write "Action: none." if no action needed, never omit

Good examples:
  "Kezia: OMNI ACC→CHUB SIT ok, reconnect to CHUB UAT when DBB moves. Action: wait for DBB UAT."
  "Huy Phan asked for full picture + estimate by Wed noon. Action: complete ADO sizing today."
  "Ha Hoang: PMO to consolidate 1 SOW for 3 projects. Action: none."
  "Tien Man Quach: is estimate on track? Action: confirm status to Tien."

Bad examples (REJECT and re-extract):
  "Discussion about the project." → too vague
  "Update from Kezia." → no content
  "Ha Hoang nói về việc PMO sẽ consolidate SOW." → not translated
```

#### Supabase write per record (v11.0 — replaces Mem0 pipe-serialization):

After extracting signals, map each to `source_items` and write to Supabase:

```python
teams_items = []
teams_actions = []
teams_decisions = []
teams_risks = []

for sig in teams_flagged:
    # ── source_items row ────────────────────────────────────────────────────
    teams_items.append({
        "source_type":  "teams_message",
        "item_id":      sig["signal_id"],
        "title":        sig["summary"][:200],
        "summary":      sig["summary"],
        "sender":       sig.get("actor"),
        "tags":         [sig["signal"]] + (["GOVERNANCE"] if sig.get("chat") == "VN-OMNI-GOV" else []),
        "market":       sig.get("opco"),
        "module":       sig.get("module"),
        "priority":     "P1" if sig["signal"] in ["URGENT","BLOCKER","INCIDENT"] else "P2",
        "is_urgent":    sig["signal"] in ["URGENT","BLOCKER","INCIDENT","DIRECTION"],
        "is_client_facing": sig.get("actor") in ["Andrea","Kay Sheng","Kezia","Angelia"],
        "item_created_at": sig.get("ts"),
        "item_updated_at": sig.get("ts"),
    })

    # ── actions: DIRECTION, BLOCKER, URGENT signals ──────────────────────────
    if sig["signal"] in ["DIRECTION","BLOCKER","URGENT"] and sig.get("next_action"):
        slug = sig["next_action"].lower().replace(" ","_")[:30]
        teams_actions.append({
            "action_key":     f"teams_message:{sig['signal_id']}:{slug}",
            "title":          sig["next_action"],
            "owner":          sig.get("owner", "Nghiem"),
            "source":         "teams_message",
            "source_ref":     sig["signal_id"],
            "module":         sig.get("module"),
            "market":         sig.get("opco"),
            "priority":       "P1" if sig["signal"] in ["URGENT","BLOCKER"] else "P2",
            "status":         "open",
            "is_client_facing": sig.get("actor") in ["Andrea","Kay Sheng","Kezia","Angelia"],
            "confidence":     0.9 if sig.get("confidence") == "high" else 0.7,
        })

    # ── decisions: DECISION signal ────────────────────────────────────────────
    if sig["signal"] == "DECISION":
        ts_date = sig.get("ts", run_date)[:10]
        slug = sig["summary"][:30].lower().replace(" ","-").replace("|","-")
        teams_decisions.append({
            "decision_key":  f"teams_message:{ts_date}:{slug}",
            "decision_date": ts_date,
            "description":   sig["summary"],
            "topic":         sig.get("module"),
            "module":        sig.get("module"),
            "market":        sig.get("opco"),
            "source":        "teams_message",
            "source_ref":    sig["signal_id"],
            "made_by":       sig.get("actor"),
            "status":        "confirmed",
        })

    # ── risks: BLOCKER or INCIDENT signal ────────────────────────────────────
    if sig["signal"] in ["BLOCKER","INCIDENT"]:
        module = (sig.get("module") or "omni").lower()
        market = (sig.get("opco") or "all").lower()
        slug   = sig["summary"][:25].lower().replace(" ","-")
        teams_risks.append({
            "risk_key":    f"{module}:{market}:{slug}",
            "title":       sig["summary"],
            "description": sig["summary"],
            "module":      sig.get("module"),
            "market":      sig.get("opco"),
            "severity":    "P1" if sig["signal"] == "INCIDENT" else "P2",
            "status":      "open",
            "owner":       sig.get("owner", "Nghiem"),
        })

# Upsert all to Supabase
if teams_items:
    upsert_source_items(sync_id=sync_id, items=teams_items)
    sources_ok.append("teams")
    print(f"[STEP 3D] supabase_source_items_upserted: type=teams_message count={len(teams_items)}")
if teams_actions:
    upsert_actions(sync_id=sync_id, actions_list=teams_actions)
    print(f"[STEP 3D] supabase_actions_upserted: count={len(teams_actions)}")
if teams_decisions:
    upsert_decisions(sync_id=sync_id, decisions_list=teams_decisions)
    print(f"[STEP 3D] supabase_decisions_upserted: count={len(teams_decisions)}")
if teams_risks:
    upsert_risks(sync_id=sync_id, risks_list=teams_risks)
    print(f"[STEP 3D] supabase_risks_upserted: count={len(teams_risks)}")

teams_urgent_count = sum(1 for s in teams_flagged if s["signal"] in ["URGENT","BLOCKER","DIRECTION"])
```

⚠️ **BLOCKED**: Do NOT write `[TEAMS+CLICKUP]` or `[TEAMS]` Mem0 entries. Teams signals are now in Supabase `source_items` with `source_type = 'teams_message'`.

⚠️ **Vietnamese rule**: Messages in Vietnamese carry the same weight as English. Always translate and summarize Vietnamese content.

---

## STEP 4 — FETCH & CACHE CLICKUP TASKS (MCP-native, no Composio)

Workspace: 90182383427 | Spaces: OMNI Products (90189534670), Bug & Issue Management (90189810586)

⛔ **DO NOT use Composio for ClickUp fetch.** Use `clickup_search` MCP tool only.
`clickup_search` covers all spaces and lists in a single call — no split calls needed.
Fetch scope: **Nghiem only** (assignees=[107626012]).

### Timestamp rules — CRITICAL

Always store and compare ClickUp timestamps as **Unix milliseconds (UTC)**.

```
CORRECT: 2026-05-24 16:46 GMT+7 = 2026-05-24T09:46:00Z = 1779615960000 ms
WRONG:   2026-05-24 16:46 GMT+7 ≠ 1748079960000 ms  ← this is a 2025 timestamp
```

Always compute timestamps from the actual current datetime via `user_time_v0`.
Never hardcode or approximate — a wrong timestamp causes FULL mode to run every sync.

Cache stores both formats:
```
last_sync_ts_ms: <unix_ms_utc>       # for comparison with task.dateUpdated
last_sync_ts_iso: <YYYY-MM-DDTHH:MM:SSZ>  # for human readability
timezone_note: UTC milliseconds
```

### 4A — Determine ClickUp Cache Mode

Use `get_latest_sync_run()` to get the last run timestamp from Supabase `sync_runs`.
Do NOT scan Mem0 for `[CLICKUP-CACHE]` entries — Mem0 is retired.

```python
latest_run = get_latest_sync_run()

if not latest_run:
    # First run — no prior sync record
    print("ClickUp cache mode: FULL (no prior sync run found)")
    last_sync_ts_ms = None
    clickup_mode = "FULL"
else:
    # Parse run_at from latest sync_run as the incremental cutoff
    from datetime import datetime, timezone, timedelta
    try:
        run_at_str   = latest_run["run_at"].replace("T"," ")[:16]
        gmt7         = timezone(timedelta(hours=7))
        last_run_dt  = datetime.strptime(run_at_str, "%Y-%m-%d %H:%M").replace(tzinfo=gmt7)
        last_sync_ts_ms = int(last_run_dt.timestamp() * 1000)
        print(f"ClickUp cache mode: INCREMENTAL (since {run_at_str} GMT+7 = {last_sync_ts_ms} ms)")
        clickup_mode = "INCREMENTAL"
    except Exception as e:
        print(f"[WARN] Could not parse sync_run.run_at: {e} — falling back to FULL mode")
        last_sync_ts_ms = None
        clickup_mode = "FULL"
```

Log: `ClickUp cache mode: FULL` or `ClickUp cache mode: INCREMENTAL (since <ISO datetime>)`

### 4B — Fetch via `clickup_search` with early-stop

**INCREMENTAL MODE:**

```python
last_sync_ts_ms = last_sync_ts_ms  # from STEP 4A via get_latest_sync_run()

changed = []
cursor = None
stop = False

while True:
    page = clickup_search(
        filters={"assignees": ["107626012"]},
        sort=[{"field": "updated_at", "direction": "desc"}],
        count=25,
        cursor=cursor
    )
    for task in page.get("results", []):
        task_updated_ms = int(task["dateUpdated"])
        if task_updated_ms <= last_sync_ts_ms:
            stop = True
            break          # all remaining tasks are older — stop pagination
        changed.append(task)
    if stop or not page.get("next_cursor"):
        break
    cursor = page["next_cursor"]

tasks = changed
print(f"ClickUp INCREMENTAL: {len(tasks)} tasks changed since last sync")
```

- If `len(tasks) == 0` → no changes since last sync; skip Mem0 cache writes; log `ClickUp INCREMENTAL: 0 changes`
- **CAP guard**: if `len(tasks) > 100` in INCREMENTAL → log `⚠️ Large changeset: {N} tasks` and proceed (do NOT abort)

**FULL MODE:**

```python
tasks = []
cursor = None

while True:
    page = clickup_search(
        filters={"assignees": ["107626012"]},
        sort=[{"field": "updated_at", "direction": "desc"}],
        count=25,
        cursor=cursor
    )
    tasks.extend(page.get("results", []))
    cursor = page.get("next_cursor")
    if not cursor:
        break

print(f"ClickUp FULL: {len(tasks)} tasks fetched")
```

Use `tasks` list for all subsequent steps (4C onward). `clickup_search` returns sufficient fields — no per-task enrichment call needed unless `description` is specifically required for a task.

⚠️ **Fields available from `clickup_search` per task**: `id`, `name`, `status`, `assignees`, `dateUpdated`, `url`, `hierarchy` (space/list/folder), `custom_id`, `taskType`, `archived`.
⚠️ **If full description needed for a specific task**: call `ClickUp:clickup_get_task` individually — only for tasks where description content is required for signal extraction.

### 4C — Upsert ClickUp tasks to Supabase + Build Urgent Snapshot

⚠️ **v11.0 CHANGE**: ClickUp tasks are upserted to Supabase `source_items`. Mem0 `[CLICKUP-CACHE][*]` structured blobs are NO LONGER WRITTEN.

```python
def resolve_list_name(task):
    return task.get("hierarchy", {}).get("subcategory", {}).get("name", "Unknown")

def derive_module(list_name: str) -> str:
    LIST_MODULE_MAP = {
        "REP": "REP", "LOOP": "LOOP", "HAP": "HAP",
        "PROMO": "PEM", "OMNI": "OMNI", "Contact Center": "CC",
        "REP MANAGER": "REP_MGR", "Bug & Issue Management": "OMNI"
    }
    return LIST_MODULE_MAP.get(list_name, "OMNI")

def derive_market(task_name: str) -> str | None:
    name_upper = task_name.upper()
    for opco in ["MY", "ID", "KH", "LA", "TW", "IN", "MM"]:
        if opco in name_upper:
            return opco
    return None

clickup_items   = []
clickup_actions = []  # overdue + blocked items → actions register
overdue_count   = 0
due_today_count = 0

gmt7 = timezone(timedelta(hours=7))
now  = datetime.now(gmt7)
now_ms = int(now.timestamp() * 1000)

for task in tasks:
    task_id    = task.get("id", "")
    task_name  = task.get("name", "")
    status     = (task.get("status", {}).get("status") or "").lower()
    priority   = (task.get("priority", {}).get("priority") or "").lower()
    due_ms     = task.get("due_date")
    list_name  = resolve_list_name(task)
    module     = derive_module(list_name)
    market     = derive_market(task_name)
    is_overdue = bool(due_ms and int(due_ms) < now_ms)
    is_urgent  = priority in ("urgent", "high") or is_overdue or status == "blocked"
    is_due_today = bool(due_ms and (
        datetime.fromtimestamp(int(due_ms)/1000, tz=gmt7).date() == now.date()
    ))

    if is_overdue:
        overdue_count += 1
    if is_due_today:
        due_today_count += 1

    due_date_iso = None
    if due_ms:
        try:
            due_date_iso = datetime.fromtimestamp(int(due_ms)/1000, tz=gmt7).strftime("%Y-%m-%d")
        except:
            pass

    # ── Internal operator tags (tags column) ─────────────────────────────────
    # These are AI-enriched tags for operator intelligence — NEVER written to ADO.
    tags = []
    if is_overdue:           tags.append("OVERDUE")
    if is_due_today:         tags.append("DUE_TODAY")
    if priority == "urgent": tags.append("URGENT")
    if status == "blocked":  tags.append("BLOCKED")
    if module:               tags.append(f"MODULE:{module}")
    if market:               tags.append(f"OPCO:{market}")

    # ── Source tags (source_tags column) ─────────────────────────────────────
    # Original ClickUp tags from the task — used by ADO sync. Never overwrite
    # with internal tags. clickup_search returns tags as list of {name, ...} dicts.
    source_tags = [
        t["name"] for t in (task.get("tags") or [])
        if isinstance(t, dict) and t.get("name")
    ]
    # Log token when tags are present
    if source_tags:
        print(f"[STEP 4C] clickup_source_tags_fetched: task={task_id} tags={source_tags}")

    clickup_items.append({
        "source_type":   "clickup_task",
        "item_id":       task_id,
        "title":         task_name,
        "summary":       f"{status} | {list_name}" + (f" | due:{due_date_iso}" if due_date_iso else ""),
        "source_url":    task.get("url"),
        "tags":          tags,          # internal operator tags — MODULE:*, OPCO:*, etc.
        "source_tags":   source_tags,   # original ClickUp tags — id, mys, mm, v1.0, etc.
        "market":        market,
        "module":        module,
        "priority":      "P1" if is_urgent else "P2",
        "status":        status,
        "assignee":      next((a.get("username") or a.get("email","") for a in task.get("assignees",[])), None),
        "due_date":      due_date_iso,
        "is_urgent":     is_urgent,
        "item_updated_at": str(task.get("dateUpdated") or ""),
    })

    # Overdue or blocked → also create an action record
    if is_overdue or status == "blocked":
        action_type = "overdue" if is_overdue else "blocked"
        slug = f"{action_type}-{task_id[:8]}"
        clickup_actions.append({
            "action_key":  f"clickup_task:{task_id}:{action_type}",
            "title":       f"[{action_type.upper()}] {task_name}",
            "owner":       "Nghiem",
            "due_date":    due_date_iso,
            "source":      "clickup_task",
            "source_ref":  task_id,
            "source_url":  task.get("url"),
            "module":      module,
            "market":      market,
            "priority":    "P1" if is_overdue else "P2",
            "status":      "open",
            "timebox":     "today" if is_overdue else "this_week",
            "confidence":  0.95,
        })

if clickup_items:
    upsert_source_items(sync_id=sync_id, items=clickup_items)
    sources_ok.append("clickup")
    tagged_count = sum(1 for t in clickup_items if t.get("source_tags"))
    print(f"[STEP 4C] supabase_source_items_upserted: type=clickup_task count={len(clickup_items)}")
    print(f"[STEP 4C] clickup_source_tags_upserted: tasks_with_source_tags={tagged_count}/{len(clickup_items)}")

if clickup_actions:
    upsert_actions(sync_id=sync_id, actions_list=clickup_actions)
    print(f"[STEP 4C] supabase_actions_upserted: count={len(clickup_actions)} (overdue+blocked)")

# full_tasks dict kept in memory for STEP 4F eligibility check
full_tasks = {task.get("id"): task for task in tasks}
```

⚠️ **BLOCKED**: Do NOT write `[CLICKUP-CACHE][<LIST>]` Mem0 entries. ClickUp tasks are now in Supabase.

### 4D — Save Cache Timestamp (Supabase sync_run, not Mem0)

⚠️ **v11.0 CHANGE**: ClickUp cache timestamp is now implicit in `sync_runs.run_at`. The separate `[CLICKUP-CACHE] last_sync_ts` Mem0 entry is RETIRED.

For INCREMENTAL mode on the next run: `cache_check_from_supabase()` reads `sync_runs.run_at` as the window boundary.

```python
# Log ClickUp stats — no separate Mem0 write needed
print(f"[STEP 4D] ClickUp: {len(tasks)} tasks upserted | overdue:{overdue_count} | due_today:{due_today_count}")
# sync_id already carries the run timestamp — downstream uses get_latest_sync_run().run_at
```

---

## ⛔ STEP 4F EXECUTION GATE — v11.1 (NON-NEGOTIABLE)

**After STEP 4C/4D complete, Claude MUST pause and verify STEP 4F will execute.**

```
BEFORE proceeding to STEP 5 or STEP 7:

✅ CHECKPOINT: Is current_sync_mode == "CACHE"?
   → YES: STEP 4F is validly skipped. Proceed to STEP 5.
   → NO:  STEP 4F MUST run. Do NOT proceed to STEP 5 until STEP 4F is complete.

✅ VERIFICATION: Have you called tool_search("ClickUp get task comments")?
   → If NO: Call it NOW before 4F-1. This is not optional.

✅ SELF-AUDIT: Are you tempted to skip STEP 4F for any of these reasons?
   - "The other steps are complete" → INVALID
   - "ClickUp tasks were already fetched" → INVALID
   - "Saving tokens" → INVALID
   - "No obvious comments needed" → INVALID
   - "Moving to context pack build" → INVALID — STEP 4F runs BEFORE context pack

If you are about to write to context_packs or call complete_sync_run()
without having executed STEP 4F: STOP. Go back and run STEP 4F.
```

**Root cause of v11.1 patch**: In the first FULL production run (2026-05-26 sync_id:a6e257b2), STEP 4F was silently skipped. The sync proceeded from ClickUp task upsert directly to decisions/risks/context pack. Result: 0 clickup_comment rows written, no reply-needed actions surfaced, no comment signals in context pack. This gate prevents that failure mode in all future runs.

---

## STEP 4F — FETCH & EXTRACT CLICKUP COMMENT SIGNALS ⭐ NEW

### ⛔ TOOL PRE-LOAD — REQUIRED FIRST ACTION IN STEP 4F

**Before doing anything else in STEP 4F, call `tool_search("ClickUp get task comments")`.**

This is mandatory because `tool_search` returns only 5 tools per call — `clickup_get_task_comments` is not guaranteed to be in the initial batch. Declaring STEP 4F skipped because the tool "wasn't available" without searching for it first is a violation.

```python
# ALWAYS run this before 4F-1 — no exceptions
tool_search(query="ClickUp get task comments")
# Confirms clickup_get_task_comments is loaded before proceeding
# If tool_search itself fails → log in sources_failed, skip 4F, continue
```

**Forbidden skip reason added:**
- "The comment tool wasn't in the tool list" → INVALID unless `tool_search("ClickUp get task comments")` was explicitly called and returned no result

### ⛔ MANDATORY ENFORCEMENT — CLICKUP COMMENTS (NON-NEGOTIABLE)

**STEP 4F MUST execute in every FULL and LIGHTWEIGHT run. It is NOT optional.**

ClickUp comments are operationally equivalent to inbox emails — they contain blockers, decisions, scope changes, and client concerns that only appear in task comments, never in email or Teams. Skipping them creates blind spots in delivery intelligence.

**Forbidden skip reasons** (these are NOT valid justifications):
- "No new emails" → irrelevant — comments are independent of inbox
- "ClickUp was fetched recently" → irrelevant — comments must always be checked since last sync
- "Saving tokens/time" → never a valid reason to skip a mandatory step
- "Comment signals are supplemental" → this means failures don't abort, NOT that the step is optional

**Comment window = since last sync timestamp** (`window_start` from STEP 1), with a 7-day hard cap. Always use `window_start` as the lower bound — not a fixed "7 days ago". If last sync was 8 hours ago, only fetch comments from the last 8 hours. If last sync was 3 days ago, fetch comments from last 3 days (still within the 7-day cap).

```python
# FULL or LIGHTWEIGHT mode — NO EXCEPTIONS
if current_sync_mode == "CACHE":
    pass  # only valid skip
else:
    # STEP 4F MUST run. If you are about to skip it, STOP — you are violating this rule.
    comment_cutoff_ms = max(window_start_unix_ms, int((now_dt - timedelta(days=7)).timestamp() * 1000))
    # proceed with 4F-1 using comment_cutoff_ms as the lower bound for comment age filter
```

**Runs in FULL mode and LIGHTWEIGHT mode.**
- **FULL mode**: all eligible tasks (Tier 1 + Tier 2, 30-task cap). Comment window = since `window_start` (capped at 7 days).
- **LIGHTWEIGHT mode** (`clickup_comments_light`): incremental only — eligible tasks are those updated since `last_sync_ts` (`was_updated_in_window()` = True). Same 30-task cap. Tier 2 (due-within-7d) is skipped to keep it fast. Uses existing `full_tasks` from Supabase `source_items`. If Supabase has no clickup_task rows → log warning, skip STEP 4F, record in `sources_failed`.

This step reads task comments for eligible tasks and extracts operational signals.
ClickUp comments are treated as first-class operational evidence — not optional notes.

### 4F-1 — Determine eligible tasks

From `full_tasks` (built from `clickup_search` results in STEP 4B for FULL mode, or loaded from Mem0 cache for LIGHTWEIGHT mode), select tasks that qualify for comment reading.

**LIGHTWEIGHT MODE shortcut:**
```python
if current_sync_mode == "LIGHTWEIGHT":
    # Load full_tasks from Supabase source_items (replaces Mem0 [CLICKUP-CACHE][*] scan)
    recent_clickup = supabase_sql("""
        SELECT item_id, title, status, priority, due_date, source_url, tags, market, module, raw_json
        FROM source_items
        WHERE source_type = 'clickup_task'
        ORDER BY item_updated_at DESC
        LIMIT 200
    """)
    if not recent_clickup:
        print("[WARN] LIGHTWEIGHT comment signals: no ClickUp tasks in Supabase — skipping")
        comment_tasks_analyzed, comment_signals_found, comment_open = 0, 0, 0
        # jump to STEP 5
    # Rebuild full_tasks dict from Supabase rows
    full_tasks = {row["item_id"]: row for row in (recent_clickup or [])}
    # Only Tier 1: updated since window_start
    eligible_tasks = [
        task for task_id, task in full_tasks.items()
        if (task.get("status") or "").lower() not in SKIP_STATUSES
        and was_updated_in_window(task)
    ][:COMMENT_TASK_CAP]
    print(f"LIGHTWEIGHT comment-eligible tasks: {len(eligible_tasks)} (updated since last sync)")
    # → proceed to 4F-2 with eligible_tasks
```

**FULL MODE — Priority tiers (process in order, stop at cap):**

**Tier 1 — Always read (highest priority):**
- Status = `in progress`, `dev in progress`, `blocked`
- Priority = `urgent` or `high`
- Task is overdue (due_date < now)
- Task was updated within the sync window (`date_updated > window_start_unix_ms`)
- Task mentioned in flagged emails or Teams messages this run (cross-reference by title keyword match)

**Tier 2 — Read if cap not reached:**
- Status = `to do`, `backlog`, `open`, `approved & to be evaluated`
- Due date within next 7 days

**Tier 3 — Skip unless specifically needed:**
- Status = `closed`, `done`, `complete`
- No updates in last 14 days

**Cap rule:** Process at most **30 tasks** per run. Always fill Tier 1 first, then Tier 2.
Log: `Comment-eligible tasks: X Tier1 + Y Tier2 = Z total (cap: 30)`

```python
from datetime import datetime, timezone, timedelta
import time

gmt7 = timezone(timedelta(hours=7))
now_unix_ms = int(time.time() * 1000)
now_dt      = datetime.now(gmt7)
window_start_unix_ms = int(window_start.timestamp() * 1000)  # from STEP 1

COMMENT_TASK_CAP = 30

TIER1_STATUSES = {"in progress", "dev in progress", "blocked"}
TIER2_STATUSES = {"to do", "backlog", "open", "approved & to be evaluated"}
SKIP_STATUSES  = {"closed", "done", "complete", "cancelled"}

def is_overdue(task):
    due = task.get("due_date")
    if not due:
        return False
    try:
        return int(due) < now_unix_ms
    except:
        return False

def due_within_days(task, days):
    due = task.get("due_date")
    if not due:
        return False
    try:
        due_dt = datetime.fromtimestamp(int(due)/1000, tz=gmt7)
        return 0 <= (due_dt - now_dt).days <= days
    except:
        return False

def was_updated_in_window(task):
    updated = task.get("date_updated")
    if not updated:
        return False
    try:
        return int(updated) >= window_start_unix_ms
    except:
        return False

# Build eligible set
tier1, tier2 = [], []
for tid, task in full_tasks.items():
    status   = (task.get("status", {}).get("status") or "").lower()
    priority = (task.get("priority", {}).get("priority") or "").lower()

    if status in SKIP_STATUSES:
        continue

    if (status in TIER1_STATUSES
            or priority in ("urgent", "high")
            or is_overdue(task)
            or was_updated_in_window(task)):
        tier1.append(task)
    elif status in TIER2_STATUSES and due_within_days(task, 7):
        tier2.append(task)

# Sort tier1 by urgency: overdue first, then updated recently
tier1.sort(key=lambda t: (-is_overdue(t), -(int(t.get("date_updated") or 0))))

eligible_tasks = (tier1 + tier2)[:COMMENT_TASK_CAP]
print(f"Comment-eligible tasks: {len(tier1)} Tier1 + {len(tier2)} Tier2 = {len(eligible_tasks)} selected (cap: {COMMENT_TASK_CAP})")
```

### 4F-2 — Load seen comment IDs + fetch new comments

**First: load already-processed comment IDs from Supabase source_items (DEDUP).**

```python
# Load seen comment IDs from source_items table (replaces Mem0 [CLICKUP-COMMENT-SIGNAL] header scan)
seen_rows = supabase_sql(f"""
    SELECT item_id FROM source_items
    WHERE source_type = 'clickup_comment'
      AND synced_at >= now() - INTERVAL '7 days'
""")
seen_comment_ids = {row["item_id"] for row in (seen_rows or [])}
print(f"Comment dedup: {len(seen_comment_ids)} comment IDs already in Supabase — will skip these")
```

Fetch latest 5 comments per task (since `comment_cutoff_ms`). Use parallel execution.

```python
def fetch_task_comments(task):
    task_id   = task.get("id")
    task_name = task.get("name", task_id)

    result, error = run_composio_tool("CLICKUP_GET_TASK_COMMENTS", {
        "task_id": task_id
    })
    if error:
        print(f"  [WARN] Comment fetch failed for '{task_name}': {error}")
        return task_id, []

    comments_raw = (result or {}).get("data", {}).get("comments") or []

    # Filter 1: since window_start (capped at 7 days) — incremental, not fixed rolling window
    recent = [
        c for c in comments_raw
        if int(c.get("date", 0)) >= comment_cutoff_ms
    ]
    # Filter 2: skip already-seen comment IDs (dedup)
    new_comments = [
        c for c in recent
        if str(c.get("id", "")) not in seen_comment_ids
    ]
    # Sort newest first, take top 5
    new_comments.sort(key=lambda c: -int(c.get("date", 0)))
    return task_id, new_comments[:5]

comment_map = {}  # task_id → list of NEW comment dicts only
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
    futures = {ex.submit(fetch_task_comments, t): t for t in eligible_tasks}
    for future in concurrent.futures.as_completed(futures):
        tid, comments = future.result()
        if comments:
            comment_map[tid] = comments

total_new_comments = sum(len(v) for v in comment_map.values())
print(f"Comments after dedup: {total_new_comments} new comments across {len(comment_map)} tasks")
```

### 4F-3 — Extract signals via single batch LLM call

Construct a batch payload and run ONE LLM extraction call for all comments.
Never process comment by comment — batch all at once.

**Low-value comment filter (pre-extraction):**
Before sending to LLM, strip comments that contain ONLY: "ok", "thanks", "thank you", "noted", "done", "will check", "please see above", "same as above", "👍", "checking", "looking into it"
EXCEPTION: Even short comments are kept if they contain approval/closure language: "approved", "confirmed", "proceed", "go ahead", "closed", "done per your request", "completed".

```python
LOW_VALUE_ONLY = {
    "ok", "thanks", "thank you", "noted", "done", "will check",
    "please see above", "same as above", "👍", "checking",
    "looking into it", "seen", "ack", "acknowledged"
}
EXCEPTION_KEYWORDS = {
    "approved", "confirmed", "proceed", "go ahead", "closed",
    "completed", "resolved", "done per", "accepted"
}

def is_low_value(comment_text: str) -> bool:
    lower = comment_text.strip().lower()
    # Low value only if it matches a low-value phrase AND contains no exception keywords
    if lower in LOW_VALUE_ONLY or len(lower) < 5:
        return not any(kw in lower for kw in EXCEPTION_KEYWORDS)
    return False

# Build batch payload
batch_items = []
for tid, comments in comment_map.items():
    task = full_tasks[tid]
    for c in comments:
        comment_text = c.get("comment_text") or c.get("text") or ""
        if not comment_text.strip() or is_low_value(comment_text):
            continue

        batch_items.append({
            "task_id":       tid,
            "task_name":     task.get("name", ""),
            "task_url":      task.get("url", ""),
            "task_status":   (task.get("status", {}).get("status") or ""),
            "task_priority": (task.get("priority", {}).get("priority") or ""),
            "task_due_date": task.get("due_date", ""),
            "task_assignee": (task.get("assignee", {}).get("username") or
                              task.get("assignee", {}).get("email") or ""),
            "task_list":     resolve_list_name(task),
            "comment_id":    c.get("id", ""),
            "comment_author": (c.get("user", {}).get("username") or
                               c.get("user", {}).get("email") or "unknown"),
            "comment_date":  c.get("date", ""),
            "comment_text":  comment_text[:500],  # cap at 500 chars per comment
        })

print(f"Comment batch size after low-value filter: {len(batch_items)} comments")
```

**Extraction prompt (single LLM call):**

```
You are an OMNI program signal extractor for a delivery manager at Niteco/Heineken APAC.

Analyze the following ClickUp task comments and extract operational signals.

SIGNAL TYPES to classify:
- ACTION: Someone needs to do something
- FOLLOW_UP: Someone asked a question or expects a response
- RISK: Something may impact scope, quality, timeline, or delivery
- BLOCKER: Work cannot continue until something is resolved
- DECISION: A stakeholder confirmed or approved a direction
- REQUIREMENT_CHANGE: Expected behavior or scope changed
- CLARIFICATION: Comment explains expected behavior
- CLIENT_CONCERN: Client or stakeholder is worried, unhappy, or pushing
- COMMITMENT: Someone promised a delivery, update, or action
- TIMELINE_IMPACT: Comment affects release, sprint, or deadline
- PRIORITY_CHANGE: Comment indicates higher/lower priority than task metadata
- OWNER_CHANGE: Comment implies a different owner or missing owner
- STATUS_MISMATCH: Comment conflicts with current task status
- SCOPE_RISK: Comment adds new scope or hidden complexity
- RELEASE_IMPACT: Comment affects current or upcoming release

METADATA MISMATCH DETECTION:
For each comment, also check if it conflicts with the task's current metadata:
- Status = Done/Closed but comment reports issue → STATUS_MISMATCH
- Priority = Normal but comment says urgent → PRIORITY_CHANGE
- No assignee but comment asks specific team → OWNER_CHANGE
- Description unchanged but comment adds new behavior → SCOPE_RISK

IGNORE comments that are low-value (ok, thanks, noted) UNLESS they confirm:
approval, closure, ownership, delivery commitment, decision, risk acceptance.

For each IMPORTANT signal found, output a JSON object:
{
  "task_id":             "<ClickUp task ID>",
  "task_name":           "<task name>",
  "task_url":            "<task URL>",
  "task_list":           "<list name: OMNI|REP|LOOP|HAP|etc>",
  "comment_author":      "<author username or email>",
  "comment_date":        "<unix ms timestamp — pass through as-is>",
  "signal_type":         "<PRIMARY signal type from list above>",
  "secondary_signals":   ["<additional signal types if applicable>"],
  "summary":             "<≤25 words: WHO said WHAT. Impact: brief.>",
  "impact":              "<delivery|timeline|scope|quality|relationship|none>",
  "urgency":             "<today|this_week|sprint|none>",
  "owner":               "<Niteco|Nghiem|client|team_member|unknown>",
  "module":              "<REP|LOOP|HAP|PEM|OMS|CC|OMNI|null>",
  "opco":                "<MY|ID|KH|LA|TW|IN|MM|ALL|null>",
  "suggested_next_action": "<specific action ≤15 words, or null>",
  "metadata_mismatch":   true/false,
  "mismatch_detail":     "<describe mismatch or null>",
  "status":              "open",
  "raw_reference":       "<first 80 chars of comment text>"
}

Output a JSON array of signal objects. Output ONLY the JSON array — no preamble.
If a comment has no operational value, do NOT include it.

TASKS AND COMMENTS TO ANALYZE:
<batch_items as JSON>
```

Parse the LLM response:
```python
import json

extracted_signals = []
try:
    raw_response = llm_call(extraction_prompt)
    extracted_signals = json.loads(raw_response)
    if not isinstance(extracted_signals, list):
        extracted_signals = []
    print(f"Signals extracted: {len(extracted_signals)} from {len(batch_items)} comments")
except Exception as e:
    print(f"[WARN] Comment signal extraction failed: {e} — skipping comment signals this run")
    extracted_signals = []
```

### 4F-4 — Enrich and finalize signals

Post-process extracted signals before Mem0 write:

```python
from datetime import datetime, timezone, timedelta

gmt7 = timezone(timedelta(hours=7))
now  = datetime.now(gmt7)

def unix_ms_to_dt(ts_str: str) -> str:
    try:
        return datetime.fromtimestamp(int(ts_str)/1000, tz=gmt7).strftime("%Y-%m-%d %H:%M GMT+7")
    except:
        return ts_str

for sig in extracted_signals:
    # Convert unix ms timestamp to readable datetime
    sig["comment_date_iso"] = unix_ms_to_dt(sig.get("comment_date", ""))

    # Infer module from task list if not set
    if not sig.get("module"):
        list_module_map = {
            "REP": "REP", "LOOP": "LOOP", "HAP": "HAP",
            "PROMO": "PEM", "OMNI": "OMNI", "Contact Center": "CC",
            "REP MANAGER": "REP_MGR", "Bug & Issue Management": "OMNI"
        }
        sig["module"] = list_module_map.get(sig.get("task_list", ""), None)

    # Infer OPCO from task name if not set
    if not sig.get("opco"):
        name_upper = (sig.get("task_name") or "").upper()
        for opco in ["MY", "ID", "KH", "LA", "TW", "IN", "MM"]:
            if opco in name_upper or opco.lower() in name_upper.lower():
                sig["opco"] = opco
                break

    # Set version and timestamp
    sig["version"]     = 1
    sig["replaced_at"] = now.strftime("%Y-%m-%d %H:%M GMT+7")
    sig["source"]      = "clickup_comment"
    sig["project"]     = "OMNI"
```

### 4F-5 — Write to Supabase

⚠️ **v11.0 CHANGE**: Comment signals now write to Supabase `source_items`, `actions`, `decisions`, and `risks`. Mem0 `[CLICKUP-COMMENT-SIGNAL]` and `[CLICKUP-COMMENT-SIGNAL][OPEN]` entries are NO LONGER WRITTEN.

```python
comment_source_items = []
comment_actions      = []
comment_decisions    = []
comment_risks        = []

for sig in extracted_signals:
    task_id      = sig.get("task_id", "")
    comment_id   = sig.get("comment_id", str(sig.get("comment_date", "")))
    signal_type  = sig.get("signal_type", "INFO")
    summary      = sig.get("summary", "")
    module       = sig.get("module")
    opco         = sig.get("opco")
    urgency      = sig.get("urgency", "none")
    is_urgent    = urgency in ("today", "this_week") or signal_type in ("BLOCKER","URGENT","RISK_ESCALATION")

    # ── source_items row (every signal) ─────────────────────────────────────
    # Inherit source_tags from parent task (original ClickUp task tags)
    # comments don't have their own source tags — they inherit from parent for ADO context
    parent_task = full_tasks.get(task_id, {})
    parent_source_tags = parent_task.get("source_tags") or []
    # fallback: if parent came from Supabase (LIGHTWEIGHT), raw_json may not have tags
    # In that case inherit what was stored on the parent source_items row
    if not parent_source_tags:
        parent_source_tags = [
            t["name"] for t in (parent_task.get("tags") or [])
            if isinstance(t, dict) and t.get("name")
            and not any(t["name"].startswith(p) for p in
                        ["MODULE:","OPCO:","PRIORITY:","MARKET:","INTERNAL:"])
        ]

    # Determine if this signal requires a reply from Nghiem
    reply_needed = signal_type in ("FOLLOW_UP", "ACTION", "BLOCKER", "CLIENT_CONCERN", "RISK_ESCALATION")
    reply_tags = (["reply-needed"] if reply_needed else [])

    comment_source_items.append({
        "source_type":   "clickup_comment",
        "item_id":       f"{task_id}:{comment_id}",
        "title":         f"[{signal_type}] {sig.get('task_name','')}"[:200],
        "summary":       summary,
        "body_excerpt":  sig.get("raw_reference", "")[:500],
        "source_url":    sig.get("task_url"),
        "sender":        sig.get("comment_author"),
        "tags":          [signal_type] + ([f"OPCO:{opco}"] if opco else []) + ([f"MODULE:{module}"] if module else []) + reply_tags,
        "source_tags":   parent_source_tags,  # inherited from parent clickup_task
        "market":        opco,
        "module":        module,
        "priority":      "P1" if is_urgent else "P2",
        "status":        sig.get("status", "open"),
        "assignee":      sig.get("owner"),
        "is_urgent":     is_urgent,
        "is_client_facing": sig.get("owner") == "client" or sig.get("metadata_mismatch", False),
        "item_created_at": sig.get("comment_date_iso"),
        # v3.0 reply tracking fields — used by omni-comment-reply-queue for live verification
        "reply_status":  "pending" if reply_needed else "not_needed",
        "raw_json": {
            "task_id":             task_id,
            "task_name":           sig.get("task_name", ""),
            "comment_id":          comment_id,
            "requester_username":  sig.get("comment_author", ""),   # who asked — used for reply detection
            "comment_date_ms":     int(sig.get("comment_date", 0)), # timestamp — latest comment after this = replied
            "signal_type":         signal_type,
            "reply_needed":        reply_needed,
        },
    })

    # ── actions: FOLLOW_UP, ACTION, BLOCKER, RISK_ESCALATION ────────────────
    if signal_type in ("ACTION","FOLLOW_UP","BLOCKER","RISK_ESCALATION","COMMITMENT") \
       and sig.get("suggested_next_action"):
        action_slug = signal_type.lower()[:20]
        comment_actions.append({
            "action_key":     f"clickup_comment:{task_id}:{comment_id}:{action_slug}",
            "title":          sig["suggested_next_action"],
            "owner":          sig.get("owner", "Nghiem"),
            "source":         "clickup_comment",
            "source_ref":     f"{task_id}:{comment_id}",
            "source_url":     sig.get("task_url"),
            "module":         module,
            "market":         opco,
            "priority":       "P1" if signal_type in ("BLOCKER","RISK_ESCALATION") else "P2",
            "status":         "open",
            "timebox":        urgency if urgency != "none" else "this_week",
            "is_client_facing": sig.get("owner") == "client",
            "confidence":     0.9 if sig.get("confidence") == "high" else 0.7,
        })

    # ── decisions: DECISION signal only ─────────────────────────────────────
    if signal_type == "DECISION":
        date_str = (sig.get("comment_date_iso") or run_date)[:10]
        slug = summary[:25].lower().replace(" ","-")
        comment_decisions.append({
            "decision_key":  f"clickup_comment:{task_id}:{date_str}:{slug}",
            "decision_date": date_str,
            "description":   summary,
            "topic":         sig.get("impact"),
            "module":        module,
            "market":        opco,
            "source":        "clickup_comment",
            "source_ref":    f"{task_id}:{comment_id}",
            "source_url":    sig.get("task_url"),
            "made_by":       sig.get("comment_author"),
            "status":        "confirmed",
        })

    # ── risks: RISK, BLOCKER, SCOPE_RISK, TIMELINE_IMPACT signals ────────────
    if signal_type in ("RISK","BLOCKER","SCOPE_RISK","TIMELINE_IMPACT","RELEASE_IMPACT"):
        mod_slug  = (module or "omni").lower()
        mkt_slug  = (opco or "all").lower()
        risk_slug = summary[:20].lower().replace(" ","-")
        comment_risks.append({
            "risk_key":    f"{mod_slug}:{mkt_slug}:{risk_slug}",
            "title":       summary[:200],
            "description": sig.get("mismatch_detail") or summary,
            "module":      module,
            "market":      opco,
            "severity":    "P1" if signal_type in ("BLOCKER","RELEASE_IMPACT") else "P2",
            "status":      "open",
            "owner":       sig.get("owner", "Nghiem"),
            "source_url":  sig.get("task_url"),
        })

# Batch upsert all comment data to Supabase
if comment_source_items:
    upsert_source_items(sync_id=sync_id, items=comment_source_items)
    print(f"[STEP 4F-5] supabase_source_items_upserted: type=clickup_comment count={len(comment_source_items)}")

if comment_actions:
    upsert_actions(sync_id=sync_id, actions_list=comment_actions)
    print(f"[STEP 4F-5] supabase_actions_upserted: count={len(comment_actions)}")

if comment_decisions:
    upsert_decisions(sync_id=sync_id, decisions_list=comment_decisions)
    print(f"[STEP 4F-5] supabase_decisions_upserted: count={len(comment_decisions)}")

if comment_risks:
    upsert_risks(sync_id=sync_id, risks_list=comment_risks)
    print(f"[STEP 4F-5] supabase_risks_upserted: count={len(comment_risks)}")

# Counters for STEP 8 summary
comment_signals_found  = len(extracted_signals)
comment_tasks_analyzed = len(comment_map)
comment_open_count     = sum(1 for s in extracted_signals if s.get("status") == "open")

signal_type_counts = {}
for s in extracted_signals:
    st = s.get("signal_type", "UNKNOWN")
    signal_type_counts[st] = signal_type_counts.get(st, 0) + 1

blockers_found   = signal_type_counts.get("BLOCKER", 0)
decisions_found  = signal_type_counts.get("DECISION", 0)
risks_found      = signal_type_counts.get("RISK", 0)
req_changes      = signal_type_counts.get("REQUIREMENT_CHANGE", 0)
mismatches_found = sum(1 for s in extracted_signals if s.get("metadata_mismatch"))
```

### 4F-6 — Response Detection + Reply Generation

**Run after 4F-4 (enrich), before 4F-5 (Mem0 write).**

Goal: For each extracted signal, determine if Nghiem needs to reply to the comment, classify the reply need, and generate a suggested reply. Add results as new fields on each signal object — no extra ClickUp API calls needed.

**Reply classification types:**

| Class | Label | Meaning |
|---|---|---|
| 1 | FYI_ONLY | No reply needed |
| 2 | ACTION_REQUIRED | Nghiem must do something and confirm |
| 3 | DIRECT_QUESTION | Someone asked Nghiem a direct question |
| 4 | DECISION_REQUIRED | Someone needs Nghiem to decide or approve |
| 5 | RISK_ESCALATION | Risk/blocker needs acknowledgement |
| 6 | FOLLOWUP_CHASE | Another person owes something — Nghiem should chase |

**Human review triggers (always flag):**
Timeline commitment, scope change, budget/capacity, client concern, delivery risk, anything involving Andrea/Kay Sheng/Angelia/Kezia.

**Extraction prompt (single LLM call — batch ALL signals together):**

```
You are an OMNI program reply advisor for Nghiem Tan Nguyen, a delivery manager at Niteco/Heineken APAC.

For each ClickUp comment signal below, determine:
1. Does this comment require Nghiem to reply? (response_needed: true/false)
2. What is the reply classification? (reply_class: 1–6)
3. If response needed, generate a suggested reply.
4. Should this go to human review before sending?

REPLY CLASSIFICATION GUIDE:
1 = FYI_ONLY — informational, no reply needed
2 = ACTION_REQUIRED — someone is waiting for Nghiem to take action and confirm
3 = DIRECT_QUESTION — comment directly asks Nghiem something
4 = DECISION_REQUIRED — comment needs Nghiem's decision/approval
5 = RISK_ESCALATION — risk or blocker needs Nghiem's acknowledgement
6 = FOLLOWUP_CHASE — another person owes a deliverable; Nghiem should chase

REPLY RULES — NON-NEGOTIABLE:
- Short and professional (2–4 sentences MAX)
- Never over-commit on timeline, scope, or budget
- Use "I will confirm with the team" when not 100% certain
- Never blame any person or team by name
- Acknowledge the concern, state next step, give a timeframe where safe
- Never auto-post — this is a DRAFT only
- Tone: direct, calm, PM-professional

HUMAN REVIEW FLAG — set human_review: true if the comment involves:
- Timeline commitment or deadline
- Scope addition or change
- Budget, capacity, or FTE
- Client or stakeholder concern (Andrea, Kay Sheng, Angelia, Kezia)
- Delivery risk or production impact
- Anything you are not >80% confident about

For each signal, output:
{
  "task_id":             "<from signal>",
  "reply_class":         <1–6>,
  "reply_label":         "<FYI_ONLY|ACTION_REQUIRED|DIRECT_QUESTION|DECISION_REQUIRED|RISK_ESCALATION|FOLLOWUP_CHASE>",
  "response_needed":     <true|false>,
  "suggested_reply":     "<draft reply text, or null if not needed>",
  "reply_confidence":    "<high|medium|low>",
  "human_review":        <true|false>,
  "human_review_reason": "<reason string or null>"
}

Output ONLY a JSON array, one object per signal, in same order as input.
Do NOT include preamble or markdown fences.

SIGNALS TO EVALUATE:
<extracted_signals as JSON — fields: task_id, task_name, signal_type, summary, comment_author, raw_reference, urgency, impact, owner, module, opco>
```

**Parse and merge results:**

```python
reply_meta = []
try:
    reply_raw = llm_call(reply_detection_prompt)
    reply_meta = json.loads(reply_raw)
    if not isinstance(reply_meta, list) or len(reply_meta) != len(extracted_signals):
        reply_meta = [{}] * len(extracted_signals)
except Exception as e:
    print(f"[WARN] Reply detection failed: {e} — signals will have no reply metadata")
    reply_meta = [{}] * len(extracted_signals)

# Merge reply fields into each signal object
for sig, meta in zip(extracted_signals, reply_meta):
    sig["reply_class"]         = meta.get("reply_class", 1)
    sig["reply_label"]         = meta.get("reply_label", "FYI_ONLY")
    sig["response_needed"]     = meta.get("response_needed", False)
    sig["suggested_reply"]     = meta.get("suggested_reply")
    sig["reply_confidence"]    = meta.get("reply_confidence", "low")
    sig["human_review"]        = meta.get("human_review", False)
    sig["human_review_reason"] = meta.get("human_review_reason")

# Summary counts for STEP 8
reply_needed_count      = sum(1 for s in extracted_signals if s.get("response_needed"))
human_review_count      = sum(1 for s in extracted_signals if s.get("human_review"))
print(f"Reply detection: {reply_needed_count} replies needed, {human_review_count} need human review")
```

**Upsert reply-needed signals as actions in Supabase (replaces `[CLICKUP-COMMENT-REPLY-QUEUE]` Mem0 write):**

```python
# Merge reply fields into each signal object (same as before)
for sig, meta in zip(extracted_signals, reply_meta):
    sig["reply_class"]         = meta.get("reply_class", 1)
    sig["reply_label"]         = meta.get("reply_label", "FYI_ONLY")
    sig["response_needed"]     = meta.get("response_needed", False)
    sig["suggested_reply"]     = meta.get("suggested_reply")
    sig["reply_confidence"]    = meta.get("reply_confidence", "low")
    sig["human_review"]        = meta.get("human_review", False)
    sig["human_review_reason"] = meta.get("human_review_reason")

# Summary counts
reply_needed_count = sum(1 for s in extracted_signals if s.get("response_needed"))
human_review_count = sum(1 for s in extracted_signals if s.get("human_review"))
print(f"Reply detection: {reply_needed_count} replies needed, {human_review_count} need human review")

# Upsert reply-needed signals as actions in Supabase
reply_actions = []
for sig in extracted_signals:
    if not sig.get("response_needed"):
        continue
    task_id    = sig.get("task_id", "")
    comment_id = sig.get("comment_id", str(sig.get("comment_date", "")))
    slug       = f"reply-{sig.get('reply_label','reply').lower()[:20]}"
    reply_actions.append({
        "action_key":     f"clickup_comment:{task_id}:{comment_id}:{slug}",
        "title":          f"[REPLY NEEDED] {sig.get('task_name','')}"[:200],
        "owner":          "Nghiem",
        "source":         "clickup_comment",
        "source_ref":     f"{task_id}:{comment_id}",
        "source_url":     sig.get("task_url"),
        "module":         sig.get("module"),
        "market":         sig.get("opco"),
        "priority":       "P1" if sig.get("human_review") else "P2",
        "status":         "open",
        "timebox":        "today" if sig.get("urgency") == "today" else "this_week",
        "is_client_facing": sig.get("human_review", False),
        "draft_reply":    sig.get("suggested_reply", "")[:2000],
        "confidence":     0.9 if sig.get("reply_confidence") == "high" else 0.7,
    })

if reply_actions:
    upsert_actions(sync_id=sync_id, actions_list=reply_actions)
    print(f"[STEP 4F-6] supabase_actions_upserted: reply_queue count={len(reply_actions)}")
```

⚠️ **BLOCKED**: Do NOT write `[CLICKUP-COMMENT-REPLY-QUEUE]` Mem0 entry. Reply actions are now in Supabase `actions` table with `source = 'clickup_comment'` and `draft_reply` populated.
⚠️ If reply detection LLM call fails → log `[WARN]`, signals still written without reply fields. Do NOT abort sync.

---

### 4F-7 — Error handling

- If `CLICKUP_GET_TASK_COMMENTS` returns error for a task → log warn, skip that task, continue
- If LLM extraction produces malformed JSON → log warn, `extracted_signals = []`, continue sync
- If reply detection LLM call fails → log warn, comment items still written to Supabase without reply fields, continue
- If Supabase upsert fails → log warn, add `"COMMENT-SIGNAL"` to `sources_failed`, continue — comment signals are supplemental, not blocking
- Add to `sources_failed` if comment extraction entirely failed: `"COMMENT-SIGNAL"`

---

## STEP 5 — FETCH CALENDAR (lookahead)

Use `outlook_calendar_search` for next 24–48 hours.
Flag: cancellations, reschedules, standup-decline patterns from Andrea.

**After fetching, upsert calendar events to Supabase:**

```python
import re
calendar_items   = []
calendar_actions = []

# ── Deterministic prep action_key (v12.4) ────────────────────────────────────
# DEDUP CONTRACT — read before writing any calendar prep action:
#   The prep action_key MUST be produced ONLY by _prep_key(event), which derives
#   it from the event's START DATE + normalized SUBJECT. The SAME meeting on the
#   SAME day ALWAYS yields the SAME key, so ON CONFLICT (action_key) dedups it.
#   NEVER hand-author / improvise a slug (e.g. "cal-my-deploy-0615",
#   "evt-mycatchup-0615") and NEVER key off the raw Graph event id — both differ
#   run-to-run and re-insert the same meeting every sync (caused 75-row P1 bloat,
#   cleaned 2026-06-14). No exceptions, no operator discretion.
def _prep_key(event) -> str:
    date = (event.get("start","") or "")[:10].replace("-", "")          # YYYYMMDD
    slug = re.sub(r"[^a-z0-9]+", "-", (event.get("subject","") or "").lower()).strip("-")[:40].strip("-")
    return f"calendar_event:{date}-{slug}:prep"

# Client/decision meeting types that warrant prep. Daily standups/scrums are
# EXCLUDED by the guard below (recurring noise, zero prep value).
PREP_KEYWORDS = ["demo","review","planning","workshop","catchup","catch up","huddle",
                 "board","alignment","align","sync","follow up","follow-up","drumbeat",
                 "scope","retrospective","steerco","kickoff","walkthrough","1:1"]
PREP_EXCLUDE  = ["daily meeting","daily scrum","stand-up","standup","scrum"]

for event in calendar_events:
    subj_l     = (event.get("subject","") or "").lower()
    event_id   = event.get("id") or _prep_key(event)   # source_items external_id
    needs_prep = (any(kw in subj_l for kw in PREP_KEYWORDS)
                  and not any(n in subj_l for n in PREP_EXCLUDE))
    tags = ["CALENDAR"]
    if needs_prep: tags.append("PREP_NEEDED")

    calendar_items.append({
        "source_type":   "calendar_event",
        "item_id":       event_id,
        "title":         event.get("subject","")[:500],
        "summary":       f"{event.get('start','')} | {','.join(event.get('attendees',[])[:3])}",
        "source_url":    event.get("web_link"),
        "tags":          tags,
        "due_date":      event.get("start","")[:10],  # YYYY-MM-DD
        "is_urgent":     False,
        "item_created_at": event.get("created_at"),
    })

    if needs_prep:
        prep_key = _prep_key(event)        # ← deterministic; NEVER substitute
        calendar_actions.append({
            "action_key":  prep_key,
            "title":       f"[PREP] {event.get('subject','')}",
            "owner":       "Nghiem",
            "due_date":    event.get("start","")[:10],
            "source":      "calendar_event",  # v12.9 canonical — DB CHECK constraint enforces; 'calendar' is auto-mapped by DB trigger but do not rely on it
            "source_ref":  event.get("id") or prep_key,
            "priority":    "P2",
            "status":      "open",
            "timebox":     "today",
        })

if calendar_items:
    upsert_source_items(sync_id=sync_id, items=calendar_items)
    sources_ok.append("calendar")
    print(f"[STEP 5] supabase_source_items_upserted: type=calendar_event count={len(calendar_items)}")

if calendar_actions:
    upsert_actions(sync_id=sync_id, actions_list=calendar_actions)
    print(f"[STEP 5] supabase_actions_upserted: calendar prep count={len(calendar_actions)}")
```

### STEP 5-EXP — Calendar prep auto-expiry ⭐ v12.9 (FULL + LIGHTWEIGHT)

Meeting-prep actions are worthless once the meeting is 2+ days past. Without this step they
accumulate (the 2026-07-02 purge archived 50+ of them). Run immediately after the STEP 5 upserts:

```sql
UPDATE actions
SET status='archived', updated_at=now(),
    raw_json = COALESCE(raw_json,'{}'::jsonb)
               || jsonb_build_object('auto_expired', CURRENT_DATE::text, 'prev_status', status)
WHERE source='calendar_event'
  AND status IN ('open','needs_review')
  AND COALESCE(due_date, run_date) < CURRENT_DATE - 2;
```

**Guards (non-negotiable):**
- Only `open`/`needs_review` — never `in_progress`/`blocked` (someone is actively on those).
- Only `source='calendar_event'` — never email/ClickUp/governance items.
- Reversible: `prev_status` retained in `raw_json`; restore = one status flip.
- Fail-open: on error, log and continue — never abort the sync.
- Count into STEP 8 summary as `cal_expired:N`.

---

## STEP 5B — SYNC PROJECT KNOWLEDGE (FULL MODE ONLY)

**Delegated to skill: `project-knowledge-sync`** — read `/mnt/skills/user/project-knowledge-sync/SKILL.md` and execute it fully.

Run silently. Append results to STEP 8 summary: `- Project docs: X indexed / Y skipped (unchanged)`
If fails → log warning, do NOT abort data sync.
**LIGHTWEIGHT MODE: skip this step entirely.**

---

## STEP 6 — FEATURE STATUS ROLLUP ⭐ v12.2 — ⚠️ MANDATORY in FULL and LIGHTWEIGHT

**Purpose:** Centralize and synchronize status at the `(OPCO, Feature)` level across ALL
sources fetched in this run. This is the anti-fragmentation layer: the latest email about
"MM Customer Module deploy" updates the same entity that its ClickUp tasks, Teams chatter,
and comments roll into. Reads omni-config v1.5 §17 + omni-utils v11.1 UTILITY 12.

(Pre-v12.2 this step was the deprecated Mem0 write slot — now repurposed.)

### STEP 6A — Load registry (once per run)

```python
registry = supabase_sql("""
    SELECT feature_key, opco, module, aliases, registry_state
    FROM feature_status WHERE registry_state != 'rejected';
""")
if not registry:
    load_feature_registry_seed()   # first-run bootstrap; idempotent
    registry = supabase_sql("SELECT feature_key, opco, module, aliases, registry_state FROM feature_status WHERE registry_state != 'rejected';")
print(f"[STEP 6A] feature_registry_loaded: rows={len(registry)}")
```

### STEP 6B — Resolve feature_key on window signals

Note: STEPs 2–4F already set `feature_key` at write-time (v12.2). STEP 6B is the
catch-all for rows written this run with `feature_key IS NULL`:

```python
unresolved = supabase_sql(f"""
    SELECT id::text, source_type, external_id, title, summary, market, module
    FROM source_items
    WHERE sync_id = '{sync_id}' AND feature_key IS NULL;
""")
# For each row: fkey = resolve_feature_key(row, registry)  — LLM alias match per UTILITY 12
# Batch update:
#   UPDATE source_items SET feature_key = <fkey> WHERE id = <id>;
# Resolution rules: OPCO mandatory (never guess); longest-alias-first; semantic
# equivalence counts AND triggers alias auto-learn; no match → '<opco>:unmapped'.
print(f"[STEP 6B] feature_keys_resolved: resolved={n_resolved} unmapped={n_unmapped} no_opco={n_none}")
```

Also backfill `actions.feature_key` for actions created this run (match via source_ref
→ source_items.feature_key).

### STEP 6C — Auto-discovery (registry grows day by day)

Group this run's `<opco>:unmapped` signals by recurring noun-phrase (Claude judgment).
Phrase in ≥2 signals for same OPCO (FEATURE_AUTODISCOVERY.min_signals_for_candidate):

```sql
INSERT INTO feature_status (feature_key, opco, module, label, aliases, registry_state)
VALUES ('<opco>:<slug>', '<opco>', '<module|null>', '<Label>', ARRAY['<phrase>'], 'candidate')
ON CONFLICT (feature_key) DO NOTHING;
-- Then re-tag the matching unmapped signals with the new candidate key.
```

Candidates: evidence rolls up, auto-supersede DISABLED until Nghiem confirms (EOD lists
candidates → confirm / merge / reject).

### STEP 6D — Rollup touched features

```python
touched = supabase_sql(f"""
    SELECT DISTINCT feature_key FROM source_items
    WHERE sync_id = '{sync_id}' AND feature_key IS NOT NULL
      AND feature_key NOT LIKE '%:unmapped';
""")
results = []
for row in touched:
    results.append(rollup_feature_status(row["feature_key"]))   # UTILITY 12
# rollup does: precedence-based status determination (DEPLOY/DECISION > INCIDENT/BLOCKER
# > URGENT > APPROVAL/DIRECTION; INFO = evidence only; INCIDENT overrides 'deployed'),
# HIGH-confidence → write status + auto-supersede satisfied open actions
#   (status='done' + raw_json.superseded_by audit; NEVER Nghiem pending-reply or
#   GOVERNANCE_REVIEW actions; NEVER candidate features),
# LOWER-confidence → conflicts[] += signal → 'status_conflict' in briefing.
changed     = [r for r in results if r["changed"]]
superseded  = sum(len(r["superseded"]) for r in results)
conflicts   = sum(r["conflicts_added"] for r in results)
print(f"[STEP 6D] feature_rollup_complete: touched={len(touched)} changed={len(changed)} superseded_actions={superseded} conflicts={conflicts}")
```

### ⛔ STEP 6 EXECUTION GATE (NON-NEGOTIABLE)

```
BEFORE proceeding to STEP 7:

✅ CHECKPOINT: Is current_sync_mode == "CACHE"?
   → YES: STEP 6 validly skipped. Proceed to STEP 7.
   → NO:  STEP 6 MUST run (FULL and LIGHTWEIGHT both).

✅ VERIFICATION: [STEP 6D] feature_rollup_complete log line printed?
   → If NO and any source_items were written this run: STOP, run STEP 6.
   → If zero source_items written this run: log
     "[STEP 6] skipped: no new signals in window" — that is the only valid skip.

Invalid skip reasons: "saving tokens", "no obvious feature mentions",
"rollup can wait for next run" — all INVALID. A DEPLOY email left un-rolled-up
is exactly the fragmentation this step exists to prevent.
```

### STEP 6 sync summary contribution

Append to STEP 8 summary:
```
🧩 Features: <touched> touched | <changed> status changes | <superseded> actions auto-superseded | <conflicts> conflicts for review | <candidates> new candidates
```

---

## STEP 7 — COMPLETE SYNC RUN + BUILD CONTEXT PACK ⚠️ MANDATORY — NEVER SKIP

### STEP 7A0 — Loop v2 outcome capture (runs after all upserts) ⭐ v12.3

Score the operator's earlier predictions against reality. Every `upsert_actions()` /
`upsert_risks()` for this run has already executed (STEPs 2–4F, Calendar), so the DB
now holds current terminal states. Emit `outcome_signal` facts for items that reached a
terminal state (hit/over/under/neutral). Idempotent (`NOT EXISTS` guard on
`out:<kind>:<ref>`), so safe every run. **Fail-open: a capture error must NEVER block
sync completion.**

```python
# requires omni-utils v11.2 — capture_outcome_signals()
from datetime import datetime, timezone, timedelta
gmt7 = timezone(timedelta(hours=7))
try:
    # Bounded 14-day scan (= omni-config LEARNING_LOOKBACK_DAYS) + idempotent guard.
    since_outcome = (datetime.now(gmt7) - timedelta(days=14)).isoformat()
    outcome = capture_outcome_signals(since_ts=since_outcome)
    print(f"[STEP 7A0] loop_v2_outcome_capture: actions={outcome['actions']} "
          f"risks={outcome['risks']} verdicts={outcome['verdicts']}")
except Exception as e:
    outcome = {"actions": 0, "risks": 0, "verdicts": {}, "error": str(e)}
    print(f"[STEP 7A0] outcome capture skipped (fail-open): {e}")
```

> First run backfills the last 14 days of already-closed items once; thereafter
> incremental. Consumed by omni-operator-learning (calibration + rule decay) — Gate 3.

### STEP 7A0-B — Dense response-outcome ledger (Loop v2.1) ⭐ v12.7

STEP 7A0 only scores items that reached a **terminal** state, on the **ranking** dimension
(hit/over/under). Items the human *ignores* (lets age) or *overrides* (reclassify / supersede
without a clean terminal status) emit nothing — the sparseness omni-operator-learning STEP 1B
itself flags ("independent of the still-sparse outcome_signal pipeline"). This pass densifies the
ledger: it assigns a **response verdict** (acted / ignored / overridden) to every surfaced action
in the 14-day window and writes it as an `outcome_signal` fact with **`kind="response"`** — a
THIRD bucket that STEP 1B's `kind=="action"`/`"risk"` filters currently ignore, so it **cannot
pollute the existing ranking calibration**. omni-operator-learning reads it in a later edit
(Stage B: acted_rate / ignored_rate / overridden_rate). **Idempotent** (upsert on
`out:resp:<key>`; a verdict may evolve ignored→acted across runs). **Fail-open: a ledger error
must NEVER block sync completion.** Runs every mode. No new table/column, no new human burden —
it only re-derives from existing columns + the STEP 2C / STEP 2B / 7A-DEDUP stamps.

```python
# Signal sources (re-derived, never re-computed elsewhere):
#   acted      ← status done/replied/closed   (incl. STEP 2C sent-reconciliation auto-close)
#   overridden ← status superseded/cancelled/rejected/needs_review  OR  raw_json.superseded_by set
#   ignored    ← self-improve STEP 2B stamp raw_json.autoage_run  OR  long-open (created >21d, still open)
#   pending    ← still open, not aged → NO fact written (enters the ledger only when it resolves)
from datetime import datetime, timezone, timedelta
gmt7 = timezone(timedelta(hours=7))
resp = {"acted": 0, "ignored": 0, "overridden": 0}
try:
    rows = supabase_sql(r"""
      SELECT a.action_key, a.title, a.owner, a.priority, a.status, a.source_type,
             a.module, a.market, a.created_at, a.updated_at,
             CASE
               WHEN lower(coalesce(a.status,'')) IN ('done','replied','closed','complete','completed')
                 THEN 'acted'
               WHEN lower(coalesce(a.status,'')) IN ('superseded','cancelled','canceled','rejected','needs_review','duplicate')
                 OR coalesce(a.raw_json->>'superseded_by','') <> ''
                 THEN 'overridden'
               WHEN (a.raw_json ? 'autoage_run')
                 OR (lower(coalesce(a.status,'')) IN ('open','active','pending','todo','in_progress','')
                     AND a.created_at < now() - interval '21 days')
                 THEN 'ignored'
               ELSE 'pending'
             END AS verdict
      FROM actions a
      WHERE (a.updated_at >= now() - interval '14 days'
             OR a.created_at >= now() - interval '14 days')
        AND coalesce(a.action_type,'') NOT IN ('SYNC_LOG','HEARTBEAT')
    """) or []
    for r in rows:
        v = r["verdict"]
        if v == "pending":                 # no signal yet — don't write
            continue
        days = None
        try:
            c, u = r.get("created_at"), r.get("updated_at")
            if c and u:
                days = (datetime.fromisoformat(str(u)) - datetime.fromisoformat(str(c))).days
        except Exception:
            pass
        upsert_knowledge_fact("outcome_signal", f"out:resp:{r['action_key']}", {
            "kind": "response", "ref": r["action_key"], "title": r.get("title"),
            "predicted_priority": r.get("priority"), "owner": r.get("owner"),
            "final_status": r.get("status"), "source_type": r.get("source_type"),
            "module": r.get("module"), "market": r.get("market"),
            "days_open": days, "verdict": v, "category": "response",
            "captured_at": datetime.now(gmt7).isoformat(),
        }, scope=(r.get("module") or "global"),
           source_skill="omni-data-sync:loop-v2.1",
           expires_at=(datetime.now(gmt7) + timedelta(days=120)).isoformat())
        resp[v] += 1
    print(f"[STEP 7A0-B] response_ledger: {resp}")
except Exception as e:
    print(f"[STEP 7A0-B] response ledger skipped (fail-open): {e}")
```

> Dense by design: an action lands a verdict the moment it resolves to acted/ignored/overridden,
> not only on a clean terminal-vs-prediction match. `pending` items stay out until they resolve,
> so the table is bounded. The verdict is pure read-only telemetry — it never surfaces to a client,
> never alters routing, never touches governance decisions; observing a governance item's response
> is fine (calibration precision is global; governance ROUTING is untouched).

### STEP 7A-DEDUP — Durable-record duplicate merge (decisions) ⭐ v12.5 — FULL mode only

**Why:** `decision_key` embeds `source_type` (`email:` / `teams_message:` / `clickup_comment:`),
so the SAME decision captured from multiple sources gets distinct keys and `upsert_decisions()`
on-key never collapses them. This is the chronic "SA-pricing / MM-deploy / ID-deploy duplicate
rows" that operator eval flagged for Memory Hygiene every run yet never resolved. This pass makes
the merge STRUCTURAL: it auto-supersedes only UNAMBIGUOUS duplicates and queues everything else
for manual hygiene. **Non-destructive (uses `superseded_by`, never DELETE), idempotent, fail-open.**

**Hard guards (constitution-level — NEVER auto-merge):**
- Governance/capacity decisions — any row whose normalized tokens or module match
  `(sow|capacity|fte|mongodb|son|scope|cost|separate|offline|migration)` are SKIPPED and only flagged.
- Auto-merge requires IDENTICAL `(market, module, normalized-token-set)` after stripping the date
  prefix and pure status words (`approved|confirmed|committed|basic|final|scheduled|pending|...`).
  Cross-module or near-miss (different token-set) duplicates are NEVER auto-merged — flag-only.
- Canonical row = `status='confirmed'` first, then earliest `created_at`. Losers get
  `superseded_by = <canonical decision_key>` (status left intact — decisions CHECK has no 'superseded').

```python
# FULL mode only (LIGHTWEIGHT skips for speed; daily FULL run is the dedup cadence).
deduped_n, dedup_flags = 0, []
if current_sync_mode == "FULL":
    try:
        # AUTO tier: supersede losers in each unambiguous, non-governance cluster.
        auto = supabase_sql(r"""
        WITH base AS (
          SELECT decision_key, status, market, module, created_at,
            (SELECT string_agg(tok,' ' ORDER BY tok) FROM (
               SELECT DISTINCT unnest(string_to_array(
                 regexp_replace(regexp_replace(decision_key,'^[^:]+:[0-9]{4}-[0-9]{2}-[0-9]{2}:',''),'[0-9]+',' ','g'),'-')) tok) t
             WHERE tok <> '' AND tok NOT IN
               ('approved','confirmed','committed','basic','final','scheduled','pending','jun','jul','date','dates','only')
            ) AS tokset
          FROM decisions WHERE superseded_by IS NULL),
        guarded AS (
          SELECT *, (lower(coalesce(tokset,'')||' '||coalesce(module,'')) ~
             '(sow|capacity|fte|mongodb|\bson\b|scope|cost|separate|offline|migration)') AS is_gov
          FROM base),
        grp AS (
          SELECT lower(coalesce(market,''))||'|'||lower(coalesce(module,''))||'|'||tokset AS sig,
                 (array_agg(decision_key ORDER BY (status='confirmed') DESC, created_at))[1] AS canon,
                 array_agg(decision_key ORDER BY (status='confirmed') DESC, created_at) AS keys,
                 bool_or(is_gov) AS any_gov, count(*) AS n
          FROM guarded GROUP BY 1 HAVING count(*) > 1)
        UPDATE decisions d SET superseded_by = g.canon
        FROM grp g
        WHERE g.any_gov = false AND d.decision_key = ANY(g.keys[2:]) AND d.superseded_by IS NULL
        RETURNING d.decision_key, g.canon;
        """) or []
        deduped_n = len(auto)

        # FLAG tier: governance clusters + cross-module/near-miss dup groups → Memory Hygiene queue.
        dedup_flags = supabase_sql(r"""
        WITH base AS (
          SELECT decision_key, market, module,
            regexp_replace(decision_key,'^[^:]+:[0-9]{4}-[0-9]{2}-[0-9]{2}:','') AS slug
          FROM decisions WHERE superseded_by IS NULL),
        noun AS (  -- coarse market+leading-noun signature for review grouping
          SELECT *, lower(coalesce(market,''))||'|'||split_part(slug,'-',2)||'-'||split_part(slug,'-',3) AS coarse
          FROM base)
        SELECT coarse, count(*) n, array_agg(decision_key) keys
        FROM noun GROUP BY coarse HAVING count(*) > 1
        ORDER BY n DESC;
        """) or []

        print(f"[STEP 7A-DEDUP] auto_merged={deduped_n} review_clusters={len(dedup_flags)}")
    except Exception as e:
        deduped_n, dedup_flags = 0, []
        print(f"[STEP 7A-DEDUP] skipped (fail-open): {e}")
```

> **Downstream contract:** every consumer that reads `decisions` (context-pack builder in STEP 7A,
> omni-daily-briefing, omni-eod-review) MUST filter `superseded_by IS NULL`. Validate this before
> relying on the pass — if a reader ignores `superseded_by`, merged rows will still render.
> Risk-table near-dups (POSM/Son-MongoDB) are intentionally OUT of scope here (risks CHECK allows
> only open/monitoring/resolved; auto-resolving a live risk is unsafe) — they stay flag-only.

### STEP 7A — Build and upsert context pack

```python
from datetime import datetime, timezone, timedelta

gmt7     = timezone(timedelta(hours=7))
run_date = datetime.now(gmt7).strftime("%Y-%m-%d")

# Build context pack from fresh Supabase data
context_pack = build_context_pack_from_supabase(run_date=run_date)

# Add sync-run metadata to pack
context_pack["sync_mode"]         = current_sync_mode
context_pack["window_label"]      = window_label
context_pack["emails_total"]      = emails_total
context_pack["emails_flagged"]    = flagged_urgent
context_pack["teams_flagged"]     = teams_urgent_count
context_pack["clickup_total"]     = len(tasks)
context_pack["clickup_overdue"]   = overdue_count
context_pack["comment_signals"]   = comment_signals_found
context_pack["reply_needed"]      = reply_needed_count
context_pack["human_review"]      = human_review_count

# Upsert context pack to Supabase
upsert_context_pack(
    pack_type   = "briefing",
    run_date    = run_date,
    sync_id     = sync_id,
    payload     = context_pack,
    cache_age_h = 0.0,
    expires_at  = (datetime.now(gmt7) + timedelta(hours=6)).isoformat(),
    is_stale    = False,
)
print(f"[STEP 7A] supabase_context_pack_upserted: type=briefing date={run_date}")
```

### STEP 7A-WI — Refill Approval Inbox (work_items) ⭐ v12.8

Runs in FULL and LIGHTWEIGHT after actions are upserted (STEP 4F) and the context
pack is built. Calls the DB-side `generate_work_items()` function, which derives
new operator work_items from open `actions` and is **idempotent** — it inserts only
actions not already represented (`NOT EXISTS` on `source_action_key`), so re-runs
never duplicate and never disturb curated/approved rows.

Governance + scope guards live INSIDE the function (gov-keyword scan over
`title || draft_reply` → `is_governance=true`, lane `needs_your_call`, never
`ready_to_send`; mirror sources `ado_work_item`/`clickup_task`/sync excluded;
priority normalized). This step only invokes it and logs the lane deltas.

```python
# STEP 7A-WI — self-populating Approval Inbox
try:
    wi = supabase_sql("SELECT * FROM generate_work_items();")  # returns created/ready/gov/ncall
    row = wi[0] if wi else {}
    print(f"[STEP 7A-WI] work_items refilled: "
          f"created={row.get('created',0)} ready_to_send={row.get('ready',0)} "
          f"governance_held={row.get('gov',0)} needs_your_call={row.get('ncall',0)}")
    # surface-only: never auto-posts here. Posting is a separate, approval-gated step.
except Exception as e:
    print(f"[STEP 7A-WI] work_items refill skipped (fail-open): {e}")
```

> **Boundary:** this step NEVER posts, sends, or approves anything. It only makes
> new drafts *visible* in the `ready_to_send` lane for Nghiem to approve. Auto-post
> is a separate approval-gated routine (`post_approved_clickup_replies`), never
> invoked from sync.

### STEP 7B — Complete sync run in Supabase

```python
# Determine final status
final_status = "complete" if len(sources_ok) > 0 else "failed"
# Only "failed" if EVERY source failed — partial success = "complete" with sources_failed populated

complete_sync_run(
    sync_id        = sync_id,
    status         = final_status,
    sources_ok     = sources_ok,
    sources_failed = sources_failed,
    summary        = (
        f"mode:{current_sync_mode} | window:{window_label} | "
        f"emails:{emails_total} | teams:{teams_urgent_count} | "
        f"clickup:{len(tasks)} | comments:{comment_signals_found} | "
        f"actions:{len(clickup_actions)+len(teams_actions)+len(comment_actions)+len(reply_actions)} | "
        f"risks:{len(clickup_actions)+len(teams_risks)+len(comment_risks)} | "
        f"outcomes:{outcome.get('actions',0)+outcome.get('risks',0)} | "
        f"responses:acted={resp.get('acted',0)}/ignored={resp.get('ignored',0)}/overridden={resp.get('overridden',0)} | "
        f"deduped:{deduped_n} | hygiene_review:{len(dedup_flags)} | "
        f"sources_failed:{','.join(sources_failed) or 'none'}"
    ),
)
print(f"[STEP 7B] supabase_sync_run_completed: id={sync_id} status={final_status}")
print(f"[STEP 7B] phase2_supabase_sync_complete: mode={current_sync_mode} sources_ok={sources_ok}")
```

### STEP 7C — Sync completion action log

```python
# v12.0: write_action() writes to Supabase actions table — Mem0 is retired
write_action(
    skill       = "SYNC",
    action_type = "COMPLETED",
    summary     = f"omni-data-sync {current_sync_mode} | supabase:{final_status} | sources:{','.join(sources_ok)}",
    metadata    = {
        "sync_id":        str(sync_id),
        "mode":           current_sync_mode,
        "run_date":       run_date,
        "sources_ok":     ",".join(sources_ok),
        "sources_failed": ",".join(sources_failed) or "none",
    },
    sync_id = sync_id,
)
```

### STEP 7D — Supabase maintenance (FULL mode only)

```python
if current_sync_mode == "FULL":
    # v12.0: Mem0 noise cleanup is retired. Run Supabase maintenance instead.
    # cleanup_old_raw_items() is called in STEP 8 — no duplicate call needed here.

    # Clean up expired knowledge_facts rows (intel_daily > 60d, intel_weekly > 90d)
    kf_cleanup = cleanup_stale_knowledge_facts()
    print(f"[STEP 7D] knowledge_facts expired rows deleted: {kf_cleanup['deleted']}")
```

### Retrieval Guide (for other skills — v11.0)

- **Latest sync status**: `get_latest_sync_run()` → reads from `sync_runs` Supabase table
- **Context pack (briefing)**: `get_latest_context_pack("briefing")` or `build_context_pack_from_supabase()`
- **Urgent actions**: query `actions WHERE status IN ('open','in_progress') ORDER BY priority, due_date`
- **Open risks**: query `risks WHERE status IN ('open','monitoring')`
- **ClickUp comments needing reply**: query `source_items WHERE source_type='clickup_comment' AND is_urgent=true`
- **Email signals**: query `source_items WHERE source_type='email' AND run_date=today`
- ⚠️ Skills MUST read data from Supabase via `build_context_pack_from_supabase()` — never call ClickUp or Outlook API directly from consumer skills

---

## STEP 8 — DELIVER SUMMARY

```
OMNI DATA SYNC — <YYYY-MM-DD HH:MM> (GMT+7) | Mode: FULL/LIGHTWEIGHT/DEEP
Supabase sync_id: <sync_id>

✅ Sources fetched:
  - Emails (Inbox): X new (Y total, Z skipped as seen) | urgent/incident: X | Supabase: ✅/❌
  - Sent emails (DAILY): X analyzed | X commitments | X decisions | X follow-ups
    Profiles updated: <list or "none"> | Supabase: ✅/❌
  [DEEP only]:
  - Sent historical scan: X batches | X emails | X style profiles built | X phrases in phrasebook
  - Teams (broad search): X messages flagged | Supabase: ✅/❌
  - Teams (VN-GOV chat): X messages read / ⚠️ error
  - Teams (Nghiem↔HuyPhan): X messages read / ⚠️ error
  - ClickUp: X Nghiem tasks (Y overdue, Z due today) | Supabase: ✅/❌
  - ClickUp Comments: X tasks analyzed → X signals found (X blockers, X decisions, X risks, X req-changes, X mismatches) | Open: X | Supabase: ✅/❌
  - Reply Queue: X replies needed (X need human review) | Supabase actions: ✅/❌
  - Calendar: X events / access denied | Supabase: ✅/❌
  - Context Pack: briefing built + upserted ✅/❌
  - Sync Run: complete ✅ / failed ❌
  - Supabase Cleanup: X source_items removed (email:X | sent:X | teams:X | clickup:X | ado:X | calendar:X)
  - Knowledge Facts: X expired rows deleted
  - Sources failed: <list or "none">

📊 Supabase writes this run:
  - source_items: email=X | sent_email=X | teams_message=X | clickup_task=X | clickup_comment=X | calendar_event=X
  - actions: X total (overdue:X | blocked:X | reply_needed:X | teams:X | calendar_prep:X)
  - decisions: X total
  - risks: X total
  - context_packs: briefing ✅
  - feature_status: <touched> touched, <changed> changed ✅
🧩 Features: <touched> touched | <changed> changes | <superseded> superseded | <conflicts> conflicts | <candidates> candidates

⚠️ COMMENT SIGNALS — ACTION NEEDED:
  - [BLOCKER] <task_name>: <summary> — Owner: <owner>
  - [STATUS_MISMATCH] <task_name>: <mismatch_detail>
  (only show if blockers_found > 0 or mismatches_found > 0)

⚠️ URGENT — ACTION NEEDED:
  - <item> — <context>

🟡 WATCH:
  - <item>

Data valid ~2 hours. Downstream skills read from Supabase via build_context_pack_from_supabase().
```

Then call `cleanup_old_raw_items(retention_days=7)` and `cleanup_stale_knowledge_facts()` (already done in STEP 7D for FULL; run for LIGHTWEIGHT here) and append counts to summary.

---

## GUARDRAILS

### Core architecture (v12.0)
- **Read omni-utils v11.2 FIRST**: All utility functions are defined there. Load `UTILITY_VERSION = "11.2"` before any step.
- **Supabase is the ONLY store**: All source data, actions, decisions, risks, context packs, and action logs go to Supabase. Mem0 is retired — do not call any Mem0 function.
- **No Mem0 fallback**: If Supabase is unavailable, `cache_check()` returns `degraded=True, mode="LIVE"`. Force FULL mode and surface the degraded flag in the summary. Do NOT fall back to Mem0.
- **`knowledge_facts` is NOT a sync buffer**: Do not write transient per-run data to `knowledge_facts`. Only durable long-term facts belong there — and only written by omni-eod-review, omni-sent-analyzer, or project-knowledge-sync.
- **`create_sync_run()` in STEP 0B is mandatory**: If it fails → set `sync_id = None`, log warning, and continue — never abort for this.
- **`complete_sync_run()` in STEP 7B is mandatory**: Always close the sync run even on partial failure. `status="complete"` if at least one source succeeded; `status="failed"` only if zero sources returned data.

### Source writes
- **`external_id` is mandatory for every source_items row**: `upsert_source_items()` conflict key is `(source_type, external_id)`. Items missing `external_id` are **skipped with a WARNING**.
- **ClickUp comment external_id**: Always call `make_comment_external_id(comment_id, task_id, created_at, author, text)`.
- **All upsert calls pass `sync_id`**: Even if `sync_id = None` — upsert helpers handle NULL FK gracefully.
- **Dedup keys are mandatory**: `action_key`, `decision_key`, `risk_key` must be unique, stable, and deterministic.
- **No full email bodies**: `body_excerpt` capped at 500 chars. Never store full raw email body.
- **Decision status accuracy**: Values MUST be one of `confirmed | proposed | pending | unclear | rejected`. `upsert_decisions()` enforces this.
- **Do NOT mix signal types**: RISK/BLOCKER/SCOPE_RISK → `upsert_risks()`. DECISION → `upsert_decisions()`. ACTION/FOLLOW_UP/reply → `upsert_actions()`.
- **`run_duplicate_audit()` in STEP 8 is mandatory**: Log result. If `audit["clean"] == False`, surface as warning. Never abort.

### ClickUp
- **ClickUp MUST use `clickup_search` MCP tool**: Never use Composio `CLICKUP_GET_FILTERED_TEAM_TASKS` for STEP 4.
- **ClickUp incremental = early-stop from sync_runs**: Stop when `task.dateUpdated <= last_sync_ts_ms` from `get_latest_sync_run()`. Never read `[CLICKUP-CACHE]` from Mem0.
- **ClickUp timestamps MUST be Unix milliseconds (UTC)**: Always derive from `user_time_v0`. Never hardcode.

### Steps 2B and 4F
- **STEP 2B (sent mail) is MANDATORY in FULL and LIGHTWEIGHT mode** — never skip.
- **STEP 4F (ClickUp comments) is MANDATORY in FULL and LIGHTWEIGHT mode** — never skip.
- **STEP 6 (Feature Rollup) is MANDATORY in FULL and LIGHTWEIGHT mode** (v12.2) — only valid skip: zero source_items written this run (log it). Rollup never writes to ClickUp/ADO; auto-supersede is confidence-gated per FEATURE_AUTOSUPERSEDE; candidates never auto-supersede.
- **feature_key tagging**: set at write-time in STEPs 2–4F where resolvable; STEP 6B backfills NULLs. OPCO is mandatory for resolution — never guess.
- **"Supplemental" means failure-tolerant, NOT optional**: Failures must never abort the main sync, but must always be attempted.
- **Comment tool pre-load**: `tool_search("ClickUp get task comments")` MUST be called at the start of STEP 4F.
- **LIGHTWEIGHT comment mode**: Load `full_tasks` from Supabase `source_items` (not Mem0). If Supabase has no rows → log warning, skip STEP 4F, record in `sources_failed`.

### Context pack
- **`build_context_pack_from_supabase()` in STEP 7A is mandatory**: Always build and upsert the briefing pack.
- **`upsert_context_pack()` dedup**: `UNIQUE(pack_type, run_date)` — re-running same day updates, never duplicates.

### Errors and partial failures
- **`sources_failed` list**: Populate throughout the run. Any Supabase upsert failure → add the source name.
- **`sources_ok` list**: Populate as each source succeeds.
- **Partial failure = `"complete"`**: Email + clickup succeeded but teams failed → `status="complete"`, `sources_failed=["teams"]`.

### Not changed
- **Email fetching**: Delegated to `omni-email-extractor`. Never call `outlook_email_search` directly here.
- **Sent analysis**: Delegated to `omni-sent-analyzer` in STEP 2B. Never analyze sent emails inline.
- **No ADO fetching**: ADO is write-only from this system.
- **Vietnamese messages**: Always translate. VN-OMNI Governance chat is primarily Vietnamese.
- **Known chats**: Always read VN-GOV and Nghiem↔HuyPhan via `read_resource` directly.

---

## CHANGELOG

| Version | Change |
|---|---|
| v12.8 | **STEP 7A-WI — auto-fill Approval Inbox** (2026-06-29). Closes the "inbox never refills on its own" gap: until now `work_items` was populated only by manual invocation, so new ClickUp/email/Teams drafts never surfaced for approval between sessions. New STEP 7A-WI (FULL + LIGHTWEIGHT, after STEP 7A context-pack build, before STEP 7B) calls the DB-side `generate_work_items()` function — idempotent (`NOT EXISTS` on `source_action_key`, so re-runs never duplicate and never disturb curated/approved/posted rows). Governance + scope guards live INSIDE the function: gov-keyword scan over `title || draft_reply` → `is_governance=true`, lane `needs_your_call`, NEVER `ready_to_send`; mirror sources (`ado_work_item`/`clickup_task`/sync/req/ado*) excluded; priority normalized (urgent/high→P1, 1/p1→P1, 2/p2→P2…); the ready_to_send send-gate requires a real draft (>40 chars, greeting/sign-off, multi-sentence) so self-notes can't masquerade as sendable. STEP **surface-only**: it makes new drafts visible for Nghiem to approve; it NEVER posts, sends, or approves. Auto-post is a separate approval-gated routine (`post_approved_clickup_replies`, clickup_comment + non-gov only) and is NEVER invoked from sync. Fail-open (never blocks sync). STEP 7A-WI log line gains `created/ready_to_send/governance_held/needs_your_call`. Manual human-reviewed edit (single non-protected file; Tier-1-class). Registry bump 12.7→12.8 in omni-config §10 follows. | Closes the precision loop's data gap: STEP 7A0 (v12.3) scores only items reaching a TERMINAL state on the RANKING dimension (hit/over/under), so items the human IGNORES (lets age) or OVERRIDES (reclassifies/supersedes without a clean terminal status) emit nothing — the sparseness omni-operator-learning STEP 1B itself flags. New STEP 7A0-B assigns a RESPONSE verdict (acted/ignored/overridden) to every surfaced action in the 14d window and writes an `outcome_signal` fact with **kind="response"** (fact_key `out:resp:<action_key>`). Crucially kind="response" is a THIRD bucket — STEP 1B only buckets `kind=="action"`/`"risk"`, so these facts are INERT to the current ranking calibration (zero pollution); the operator-learning consumer is a separate later edit (Stage B). Verdict re-derived from existing signals only (status; raw_json.superseded_by; self-improve STEP 2B raw_json.autoage_run stamp; long-open created>21d) — no new table/column, no new helper (calls existing upsert_knowledge_fact), no omni-utils (protected) change, no new human burden. Idempotent (upsert; verdict may evolve ignored→acted), fail-open (never blocks sync), runs every mode, pure read-only telemetry (never surfaces to client, never alters routing/governance). STEP 7B summary gains `responses:acted=A/ignored=I/overridden=O`. Manual human-reviewed edit (single non-protected file; Tier-1-class). Registry bump 12.5→**12.7** in omni-config §10 follows (clears the deferred 12.6 row too). |
| v12.6 | **STEP 2C — sent-vs-open-actions reconciliation** (2026-06-23). Root-cause fix for stale `reply-needed`/`follow-up` carryovers (operator correction 2026-06-23: Andrea SA-Loop reply-action surfaced as open although already answered in Sent Items; broader sweep closed 8 / superseded 17 / flagged 64 needs_review, P1 open 68→23). Cause: STEP 2/2B sent fetch is window-scoped, so a reply sent before the window but after the action was created is invisible; nothing reconciled sent mail against open reply actions. New STEP 2C (FULL/LIGHTWEIGHT) loads open email-sourced reply/follow-up actions, does its OWN sent fetch back to the oldest open action's date (NOT the sync window), and auto-closes (status=done, reply_status=replied) on a confident thread match (conversationId or normalized-subject) where sent_at > inbound_ask_at. Heuristic-only matches → needs_review, never auto-closed; governance/capacity rows require an explicit conversationId match. Fail-open + idempotent; out of scope for clickup_task/ADO/calendar-prep. Summary gains `sent_reconciled:N | reconcile_review:N`. Pairs with operator_rule rule:sync:stale-action-supersede (STEP 0A2 behavioral guard). No utils/config DDL change; registry bump 12.5→12.6 in omni-config §10 follows on approval. |
| v12.5 | **STEP 7A-DEDUP — structural duplicate-decision merge** (2026-06-21). Root-cause fix for the recurring "SA-pricing/MM-deploy/ID-deploy duplicate decision rows" that operator eval flagged for Memory Hygiene daily (06-14→21) but were never cleared. Cause: `decision_key` embeds `source_type`, so the same decision from email+teams+comment yields distinct keys that `upsert_decisions()` on-key cannot collapse. New STEP 7A-DEDUP (FULL mode only, after 7A0, before 7A) runs a post-upsert semantic merge: AUTO tier supersedes losers only in unambiguous clusters sharing identical `(market, module, normalized-token-set)` after stripping date prefix + pure status words, via the dedicated `superseded_by` column (non-destructive — no DELETE; decisions CHECK has no 'superseded' status). HARD GUARD: governance/capacity rows (`sow|capacity|fte|mongodb|son|scope|cost|separate|offline|migration`) are NEVER auto-merged. FLAG tier queues cross-module/near-miss clusters for manual hygiene. Idempotent + fail-open (never blocks sync). Summary gains `deduped:N | hygiene_review:N`. Dry-run on live data: 2 clean auto-merges (MM customer-module REP, SA pricing OMNI), governance clusters correctly skipped. Risks intentionally out of scope (auto-resolving a live risk is unsafe). Downstream contract: decision readers MUST filter `superseded_by IS NULL` (validate omni-daily-briefing/omni-eod-review/context-pack builder before relying on the pass). No utils/config dependency change; registry bump 12.4→12.5 in omni-config §10 follows on approval. |
|---|---|
| v12.4 | **STEP 5 deterministic calendar prep_key** (2026-06-14). Root-cause fix for cross-run duplicate prep actions (75 stale/dup rows cleaned this date; had inflated open P1 199→137). `_prep_key(event)` now derives the prep `action_key` solely from event START DATE + normalized SUBJECT slug (`calendar_event:<YYYYMMDD>-<subject-slug>:prep`) — stable run-to-run, recurrence-correct (per-day), human-readable. Added a hard DEDUP CONTRACT comment: NEVER hand-author a slug, NEVER key off the raw Graph event id (both vary per run and defeat `ON CONFLICT (action_key)`). Corrected `PREP_KEYWORDS` (added catchup/catch up/huddle/board/alignment/align/sync/follow-up/drumbeat/scope/steerco/kickoff/walkthrough) and added `PREP_EXCLUDE` to drop daily standups/scrums. Standardized prep `source` to `"calendar"` (was inconsistently `"calendar_event"`). No utils/config dependency change. |
| v12.3 | **Loop v2 — outcome capture wired (Gate 2)** (2026-06-14). New STEP 7A0 calls `capture_outcome_signals(since_ts=now−14d)` AFTER all `upsert_actions()`/`upsert_risks()` (STEPs 2–4F, Calendar), before context-pack build. Emits `outcome_signal` facts scoring each terminal action/risk vs the operator prediction (hit/over/under/neutral). Fail-open (never blocks sync); idempotent (NOT EXISTS guard). STEP 7B summary gains `outcomes:N`. Requires omni-utils v11.2. NOTE: omni-config §10 EXPECTED_SKILL_VERSIONS still lists data-sync 12.2 + utils 11.1 — a 2-line registry bump follows; drift audit will correctly flag until then. |
| v12.2 | **Feature Status Rollup** (2026-06-11). STEP 6 repurposed from deprecated Mem0 slot to FEATURE ROLLUP — mandatory in FULL/LIGHTWEIGHT with execution gate (mirrors STEP 4F gate pattern). STEP 6A registry load + first-run seed bootstrap; STEP 6B feature_key backfill (write-time tagging added to STEPs 2–4F); STEP 6C auto-discovery (≥2 recurring unmapped signals → candidate row, registry grows daily); STEP 6D rollup_feature_status() per touched key with confidence-gated auto-supersede (audit in raw_json.superseded_by). STEP 8 summary gains Features line. Requires omni-utils v11.1 (feature_status DDL applied 2026-06-11) + omni-config v1.5 (SA added to OPCOS). |
| v12.0 | **Supabase-only mode** (2026-05-27). Mem0 fully retired — no reads, writes, fallbacks, or atomic entries from this skill. omni-utils bumped to v11.0. STEP 4A: ClickUp incremental window from `get_latest_sync_run()` (replaces `[CLICKUP-CACHE]` Mem0 scan). STEP 1: `get_latest_sync_run()` only — no `[DATA-SYNC]` Mem0 fallback. STEP 2B: removed "atomic Mem0 writes allowed" comment — omni-sent-analyzer v2.0 writes to Supabase. STEP 7C: `write_action()` writes to Supabase actions table. STEP 7D: replaced Mem0 noise cleanup with `cleanup_stale_knowledge_facts()`. STEP 8: removed `mem0_health_check()` call and Mem0 health output line. GUARDRAILS: removed all Mem0 rules; added `knowledge_facts` scope restriction. ROLLBACK: updated to Supabase-only rollback path. TEST CHECKLIST: updated Mem0-specific test cases. |
| v12.1 | **STEP 4F-5 reply tracking** (2026-05-29). `reply_status` (`pending`/`not_needed`) and `raw_json.requester_username` + `raw_json.comment_date_ms` written on every clickup_comment row. `reply-needed` tag added to tags array for FOLLOW_UP/ACTION/BLOCKER/CLIENT_CONCERN/RISK_ESCALATION signals. Used by `omni-comment-reply-queue` v3.0 for live reply verification. Requires DDL: `ALTER TABLE source_items ADD COLUMN reply_status text DEFAULT 'pending'`. |
| v11.3 | **Idempotent upserts + duplicate audit** (2026-05-27). Bumped to omni-utils v10.2. `upsert_source_items` conflict key changed to `(source_type, external_id)`. `run_duplicate_audit()` added as mandatory STEP 8 call. |
| v11.2 | **STEP 4C — source_tags column** (2026-05-26). Fixes data-modeling bug: ClickUp original tags now written to `source_tags`; internal operator tags stay in `tags`. STEP 4F-5: comment rows inherit `source_tags` from parent task. |
| v11.1 | **BUG FIX — STEP 4F EXECUTION GATE** (2026-05-26). Hard gate added between STEP 4D and STEP 4F. Any path reaching `complete_sync_run()` without STEP 4F having run is flagged as violation. |
| v11.0 | **Phase 2 — Supabase as PRIMARY structured cache** (2026-05-25). All structured Mem0 writes retired. Supabase writes via omni-utils v10.0 helpers. |
| v10.2 | **STEP 4 — MCP-native ClickUp incremental sync** (2026-05-24). Replaced Composio with `clickup_search` MCP tool + `dateUpdated` early-stop pagination. |
| v10.1 | **STEP 7B — Atomic Noise Cleanup** (2026-05-24). After FULL rebuild, identify and delete same-day atomic Mem0 noise entries. |
| v10.0 | **Verbatim Mem0 cache writes**: All structured cache writes use `write_structured_cache_verbatim()`. |
| v9.1 | **BUG FIX — STEP 4F tool pre-load**: Mandatory `tool_search("ClickUp get task comments")` as FIRST action in STEP 4F. |
| v9.0 | **STEP 4F-6 — Comment Reply Detection**: Batch LLM reply classification. |
| v8.0 | **BUG FIX — MANDATORY STEP ENFORCEMENT + DEDUP**: STEP 2B and STEP 4F mandatory. Comment dedup. Comment window capped 7 days. |
| v7.0 | **LIGHTWEIGHT comment signals**: STEP 4F in `clickup_comments_light` mode. |
| v6.0 | **Phase 1 — ClickUp Comment Signal support**: STEP 4F added. |
| v5.1 | **BUG FIX STEP 4B**: Split CLICKUP_GET_FILTERED_TEAM_TASKS into two separate calls. |
| v5.0 | Added STEP 2B: delegates sent email analysis to `omni-sent-analyzer`. |
| v4.4 | STEP 3D Teams extraction rewritten to produce NormalizedSignal objects. |
| v4.3 | Added omni-config as first read dependency. |
| v4.2 | Extracted all four shared utilities to omni-utils. |
| v4.1 | `mem0_health_check()`: auto-purge INTEL[DAILY] >60 days; auto-purge ACTION[DECISION] >30 days. |
| v4.0 | `get_context_pack()` added as 4th shared utility. |
| v3.0 | `write_action()` v2: size cap, overflow, date-tagged, standard schema. |
| v2.1 | STEP 4: Added Bug & Issue Management list. |
| v2.0 | STEP 3 rewritten: structured batch LLM extraction. |
| v1.0 | Initial version. |

---

## TEST CHECKLIST — omni-data-sync v12.2

```
FEATURE ROLLUP TESTS (v12.2)
[ ] TC-F01 STEP 6A: registry loaded; empty table → load_feature_registry_seed() called once
[ ] TC-F02 STEPs 2-4F: items carry feature_key where resolvable at write-time
[ ] TC-F03 STEP 6B: NULL feature_key rows this run → resolved or '<opco>:unmapped'; no-OPCO rows stay NULL
[ ] TC-F04 STEP 6C: 2+ recurring unmapped phrases same OPCO → candidate row created, signals re-tagged
[ ] TC-F05 STEP 6D: touched features rolled up; log line feature_rollup_complete printed
[ ] TC-F06 Auto-supersede: high-conf DEPLOY → linked open actions done + raw_json.superseded_by; audit in feature_status.superseded_actions
[ ] TC-F07 Lower-conf signal → conflicts[] appended, status unchanged
[ ] TC-F08 STEP 6 gate: skipping with new source_items written → blocked
[ ] TC-F09 LIGHTWEIGHT mode runs STEP 6 after 4F
[ ] TC-F10 STEP 7A context pack contains feature_rollup array
[ ] TC-F11 STEP 8 summary contains Features line
```

## TEST CHECKLIST — omni-data-sync v12.0 (regression)

Run after deploying to verify Supabase-only integration end-to-end.

```
[ ] TC-01  STEP 0A: cache_check() returns hit_type="supabase_sync_run" on second run
[ ] TC-02  STEP 0A: cache_check() returns mode="CACHE" within 2h, mode="LIVE" after 5h
[ ] TC-03  STEP 0A: cache_check() Supabase unavailable → degraded=True, mode="LIVE" → FULL mode forced
[ ] TC-04  STEP 0B: create_sync_run("FULL") returns valid UUID — verify row exists in sync_runs
[ ] TC-05  STEP 0B: create_sync_run("LIGHTWEIGHT") accepted — CHECK constraint allows it
[ ] TC-06  STEP 0B: create_sync_run() failure → sync_id=None, sync continues (no abort)

[ ] TC-07  STEP 1: get_latest_sync_run() returns run_at timestamp used as window boundary
[ ] TC-08  STEP 1: No Supabase record (first run) → 18h default window — NO Mem0 [DATA-SYNC] read

[ ] TC-09  STEP 2: email_records → upsert_source_items(source_type="email") → rows in source_items
[ ] TC-10  STEP 2: Re-run same item_id → ON CONFLICT updates, single row remains
[ ] TC-11  STEP 2: Email body NOT stored — only summary + body_excerpt (max 500 chars)
[ ] TC-12  STEP 2: sources_ok includes "email" on success

[ ] TC-13  STEP 2B: sent_records → upsert_source_items(source_type="sent_email") → rows written
[ ] TC-14  STEP 2B: decision_records → upsert_decisions() with status="confirmed" and made_by="Nghiem"
[ ] TC-15  STEP 2B: No Mem0 write of any kind — no [COMM-STYLE], no [PHRASEBOOK], no [ACTION]

[ ] TC-16  STEP 3D: teams_items → upsert_source_items(source_type="teams_message") → rows written
[ ] TC-17  STEP 3D: DIRECTION/BLOCKER/URGENT signals → upsert_actions() with correct action_key format
[ ] TC-18  STEP 3D: DECISION signal → upsert_decisions() with status="confirmed"
[ ] TC-19  STEP 3D: BLOCKER/INCIDENT signal → upsert_risks() with correct risk_key format

[ ] TC-20  STEP 4A: get_latest_sync_run() used for incremental cutoff — NO Mem0 [CLICKUP-CACHE] scan
[ ] TC-21  STEP 4A: No Supabase record → FULL mode (not Mem0 fallback)
[ ] TC-22  STEP 4C: clickup_items → upsert_source_items(source_type="clickup_task") → rows written
[ ] TC-23  STEP 4C: overdue tasks → upsert_actions() with action_key="clickup_task:<id>:overdue"
[ ] TC-24  STEP 4C: blocked tasks → upsert_actions() with action_key="clickup_task:<id>:blocked"
[ ] TC-25  STEP 4D: No Mem0 timestamp entry written — next run reads window from sync_runs.run_at

[ ] TC-26  STEP 4F-1 LIGHTWEIGHT: full_tasks loaded from Supabase source_items, not Mem0
[ ] TC-27  STEP 4F-2: seen_comment_ids loaded from Supabase source_items WHERE source_type='clickup_comment'
[ ] TC-28  STEP 4F-5: extracted_signals → upsert_source_items(source_type="clickup_comment")
[ ] TC-29  STEP 4F-5: BLOCKER signals → upsert_risks() with risk_key="<module>:<market>:<slug>"
[ ] TC-30  STEP 4F-5: DECISION signals → upsert_decisions() with status="confirmed"
[ ] TC-31  STEP 4F-5: ACTION/FOLLOW_UP signals → upsert_actions() with action_key includes comment_id
[ ] TC-32  STEP 4F-6: response_needed=true signals → upsert_actions() with draft_reply populated

[ ] TC-33  STEP 5: calendar_events → upsert_source_items(source_type="calendar_event")
[ ] TC-34  STEP 5: PREP_NEEDED events → action_key=_prep_key()="calendar_event:<YYYYMMDD>-<subject-slug>:prep" (deterministic; same meeting+day re-run = 1 row, NOT raw Graph id, NOT hand-authored slug); standups/scrums excluded; source="calendar"

[ ] TC-35  STEP 7A: build_context_pack_from_supabase() returns non-empty dict with all required fields
[ ] TC-36  STEP 7A: upsert_context_pack("briefing") → row in context_packs, UNIQUE constraint works on re-run
[ ] TC-37  STEP 7B: complete_sync_run(sync_id, "complete", sources_ok, sources_failed) → status updated
[ ] TC-38  STEP 7B: partial failure (e.g. teams failed) → status="complete" with sources_failed populated
[ ] TC-39  STEP 7B: all sources failed → status="failed"
[ ] TC-40  STEP 7C: write_action() writes row to Supabase actions table — NOT to Mem0
[ ] TC-41  STEP 7C: action_key format includes skill="SYNC" and second-precision timestamp
[ ] TC-42  STEP 7D: cleanup_stale_knowledge_facts() runs in FULL mode — returns deleted count
[ ] TC-43  STEP 7D: No Mem0 noise scan, no mem0_list(), no mem0_delete() calls

[ ] TC-44  STEP 8: summary shows Supabase write counts per source_type
[ ] TC-45  STEP 8: summary does NOT include Mem0 health line
[ ] TC-46  STEP 8: cleanup_old_raw_items(7) runs and reports deleted count
[ ] TC-47  STEP 8: run_duplicate_audit() runs and reports clean/violations

[ ] TC-48  Backward compat: downstream get_context_pack("briefing") returns source="supabase", degraded=False
[ ] TC-49  Backward compat: cache_check() hit_type="supabase_sync_run" after a full run
[ ] TC-50  Degraded: if Supabase unreachable → cache_check() returns degraded=True, mode="LIVE" → FULL mode forced, no Mem0 fallback
```

---

## ROLLBACK PLAN

### Trigger conditions
Roll back to v11.3 if:
- Supabase MCP tool becomes consistently unavailable (more than 2 consecutive runs fail)
- `create_sync_run()` fails consistently
- `build_context_pack_from_supabase()` returns empty or malformed data affecting briefing
- `omni-daily-briefing` or `omni-eod-review` report `degraded=True` for more than 2 consecutive runs

### Rollback procedure

**Step 1 — Restore omni-data-sync to v11.3**
```
Replace /mnt/user-data/outputs/omni-data-sync-v12-SKILL.md with the v11.3 backup.
(v11.3: last version before Supabase-only migration)
```

**Step 2 — Restore omni-utils to v10.2**
```
Replace omni-utils with the v10.2 backup.
(v10.2: Supabase-primary with Mem0 atomic fallback)
```

**Step 3 — Run FULL sync to verify**
```
Run omni-data-sync FULL manually.
Confirm source_items, actions, decisions, risks rows are written to Supabase.
Confirm cache_check() returns mode="CACHE" within 2 minutes.
```

**Step 4 — Log the rollback via write_action()**
```python
write_action(
    skill="SYNC",
    action_type="ROLLBACK",
    summary="omni-data-sync v12.0 rollback — reverted to v11.3. Reason: <trigger condition>.",
)
```

### Graceful degradation (no full rollback needed)
If Supabase is intermittently unavailable:
- `cache_check()` returns `degraded=True, mode="LIVE"` → forces FULL mode
- `get_context_pack()` returns `degraded=True` with empty data
- briefing and EOD skills surface `degraded=True` warning to user
- No manual rollback needed — system self-heals on next successful sync run
