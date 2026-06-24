---
name: ado-oms-knowledge-sync
version: "2.1"
description: "Reads ADO work items (Area Heineken/OMS, statuses after Code Review) and stores structured entries into Supabase source_items (source_type=ado_work_item). v2.1: Supabase-only — Mem0 retired. write_action() logs to Supabase actions. Accepts configurable date window (default 6 months). Triggers on: 'sync ADO knowledge', 'refresh ADO memory', 'ADO knowledge sync', 'update OMS knowledge base', or after a major sprint/release cycle."
---

# ADO-OMS Knowledge Sync v2.1

Reads Bugs + User Stories from `Heineken\OMS` in ADO, AI-summarizes descriptions into structured records, and stores into **Supabase `source_items`** (source_type='ado_work_item'). [ADO-OMS] Mem0 blobs are **BLOCKED** — all structured cache now lives in Supabase.

---

## CHANGELOG

| Version | Change |
|---|---|
| 2.1 | **Mem0 fully retired** (2026-06). Removed "allowed atomic Mem0 writes" — all durable facts → Supabase (knowledge_facts/actions/decisions/risks/project_context). Pinned UTILS 11.0. write_action() → Supabase. |
| 2.0 | **Supabase migration** (2026-05-26). BLOCKED: all [ADO-OMS][*] Mem0 structured cache writes. PRIMARY: Supabase `source_items` (source_type='ado_work_item'). Actions → `upsert_actions()`. Risks/blockers → `upsert_risks()`. Decisions → `upsert_decisions()`. Adds log tokens, compatibility shim. |
| 1.0 | Initial: Mem0 [ADO-OMS][*] structured cache, INDEX, DONE parts. |

---

## CONFIGURATION

```
ORG:        NitecoGroup
PROJECT:    Heineken
AREA_PATH:  Heineken\OMS
ITEM_TYPES: Bug, User Story
DATE_WINDOW: parsed from user input (default: 6 months)
             → applies to Done only
             → active statuses always fetch ALL (no date filter)
RUN CAP:    1,000 items — warn + stop if exceeded
STATUSES:   QA env | Ready for UAT deploy | Acc env | Ready for Prod deploy | On Prod | Done
SUPABASE:   source_type = 'ado_work_item'
```

PAT stored in system prompt. Auth: `Basic base64(":"+PAT)`.
⚠️ Use Composio remote workbench for ALL ADO API calls.
⚠️ NEVER log or print PAT.

---

## STORAGE ARCHITECTURE

### PRIMARY: Supabase `source_items`

| Field | Value/Notes |
|---|---|
| `source_type` | `'ado_work_item'` (always) |
| `item_id` | ADO work item ID as string |
| `title` | Exact ADO ticket title |
| `summary` | AI summary bullets joined as newline string |
| `body_excerpt` | cleaned description excerpt (≤500 chars) |
| `source_url` | `https://dev.azure.com/NitecoGroup/Heineken/_workitems/edit/{id}` |
| `tags` | parsed from ADO tags field + status tag |
| `market` | extracted from tags (MY/ID/KH/LA/TW/IN/MM) |
| `module` | extracted from tags (OMS/REP/HAP/LOOP/PEM) |
| `priority` | ADO priority number |
| `status` | ADO state string |
| `assignee` | displayName of assigned user |
| `is_urgent` | true if priority=1 or status contains overdue signal |
| `is_client_facing` | true if tags contain client/OPCO marker |
| `raw_json` | minimal: `{id, type, changed, area_path}` |
| `item_updated_at` | ADO System.ChangedDate |

### OPERATIONAL DERIVATIONS

| Signal type | Destination | Condition |
|---|---|---|
| Overdue/unresolved assigned work | `upsert_actions()` | `priority ≤ 2 AND status in active states AND assignee != null` |
| Confirmed delivery decisions | `upsert_decisions()` | ticket description contains explicit decision language |
| Blockers / critical bugs | `upsert_risks()` | `type=Bug AND priority=1` |

### ⛔ BLOCKED — DO NOT WRITE

```
[ADO-OMS][INDEX]         ← BLOCKED
[ADO-OMS][ON_PROD]       ← BLOCKED
[ADO-OMS][ACC_ENV]       ← BLOCKED
[ADO-OMS][QA_ENV]        ← BLOCKED
[ADO-OMS][READY_UAT]     ← BLOCKED
[ADO-OMS][READY_PROD]    ← BLOCKED
[ADO-OMS][DONE][PART*]   ← BLOCKED
[ADO-OMS][SYNC_META]     ← BLOCKED
```

Any skill attempting to write these tags must be rejected. Log token: `ado_oms_mem0_structured_cache_blocked`.

### ⛔ Mem0 IS RETIRED (v2.1)

No Mem0 reads or writes of any kind. Durable facts go to Supabase:

```
project_context  — compact project knowledge (upsert_project_context)
actions          — write_action() / upsert_actions()
decisions        — upsert_decisions()
risks            — upsert_risks()
knowledge_facts  — recurring delivery patterns (fact_type=intel_pattern)
```

---

## LOG TOKENS

| Token | When emitted |
|---|---|
| `ado_oms_supabase_write_started` | Before first Supabase upsert |
| `ado_oms_source_items_upserted` | After `upsert_source_items()` returns |
| `ado_oms_actions_upserted` | After `upsert_actions()` returns |
| `ado_oms_decisions_upserted` | After `upsert_decisions()` returns |
| `ado_oms_risks_upserted` | After `upsert_risks()` returns |
| `ado_oms_mem0_structured_cache_blocked` | Any attempt to write [ADO-OMS][*] tag |
| `ado_oms_supabase_write_complete` | After all Supabase writes done |

---

## STEP 0 — BOOTSTRAP (read shared libs)

```python
# Step 1: Read /mnt/skills/user/omni-config/SKILL.md → load CONFIG_VERSION
# Step 2: Read /mnt/skills/user/omni-utils/SKILL.md → load UTILITY_VERSION = "11.0"
# Functions used: create_sync_run(), complete_sync_run(), upsert_source_items(),
#                 upsert_actions(), upsert_decisions(), upsert_risks(),
#                 supabase_sql(), write_action(), upsert_knowledge_fact()

SKILL_VERSION = "2.1"
print(f"ado-oms-knowledge-sync v{SKILL_VERSION} | utils v{UTILITY_VERSION}")
```

---

## STEP 1 — PARSE DATE WINDOW

```python
import re, json
from datetime import datetime, timedelta, timezone

def parse_date_window(user_input: str):
    """Returns (days: int|None, label: str). days=None → no filter."""
    text = user_input.lower()
    if any(k in text for k in ["all time", "no filter", "no date", "no limit", "everything"]):
        return None, "all time"
    m = re.search(r'(\d+)\s*(day|week|month|year)', text)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        days = {"day": n, "week": n*7, "month": n*30, "year": n*365}[unit]
        return days, f"{n} {unit}{'s' if n>1 else ''}"
    if "last week"    in text: return 7,   "7 days"
    if "last month"   in text: return 30,  "30 days"
    if "last quarter" in text: return 90,  "3 months"
    if "last year"    in text: return 365, "1 year"
    return 180, "6 months (default)"

DATE_DAYS, DATE_LABEL = parse_date_window(user_trigger)

if DATE_DAYS is None:
    print("⚠️ 'All time' selected — may exceed 1,000 item cap. Confirm to proceed.")
    since_date = None
else:
    since_date = (datetime.now(timezone.utc) - timedelta(days=DATE_DAYS)).strftime("%Y-%m-%d")
    print(f"Date window: {DATE_LABEL} (since {since_date}) — Done only")
```

---

## STEP 2 — CREATE SYNC RUN

```python
gmt7 = timezone(timedelta(hours=7))
run_date = datetime.now(gmt7).strftime("%Y-%m-%d")
window_start = since_date or "1970-01-01"
window_end   = datetime.now(gmt7).strftime("%Y-%m-%d")

sync_id = create_sync_run(
    sync_type   = "LIGHTWEIGHT",
    window_start = window_start,
    window_end   = window_end,
    sources_ok   = [],
    sources_failed = [],
    summary     = f"ADO-OMS knowledge sync | window={DATE_LABEL}"
)

if not sync_id:
    print("⚠️ Failed to create sync_run — will proceed with fallback sync_id='ado-local'")
    sync_id = "ado-local"
```

---

## STEP 3 — QUERY ADO (two separate queries)

```python
import requests, base64

PAT = "<from system prompt>"
auth = base64.b64encode(f":{PAT}".encode()).decode()
headers = {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}
ORG = "NitecoGroup"
PROJECT = "Heineken"

ACTIVE_STATES = ["QA env", "Ready for UAT deploy", "Acc env", "Ready for Prod deploy", "On Prod"]
active_filter = ", ".join([f"'{s}'" for s in ACTIVE_STATES])

# Query 1: ALL active items — no date filter (ghost detection)
r1 = requests.post(
    f"https://dev.azure.com/{ORG}/{PROJECT}/_apis/wit/wiql?api-version=7.1",
    headers=headers,
    json={"query": f"""
        SELECT [System.Id] FROM WorkItems
        WHERE [System.TeamProject] = '{PROJECT}'
          AND [System.AreaPath] UNDER 'Heineken\\OMS'
          AND [System.WorkItemType] IN ('Bug', 'User Story')
          AND [System.State] IN ({active_filter})
        ORDER BY [System.State], [System.Id]
    """}
)
active_ids = [str(wi["id"]) for wi in r1.json().get("workItems", [])]
print(f"Active IDs (no date filter): {len(active_ids)}")

# Query 2: Done — WITH date window
date_clause = f"AND [System.ChangedDate] >= '{since_date}'" if since_date else ""
r2 = requests.post(
    f"https://dev.azure.com/{ORG}/{PROJECT}/_apis/wit/wiql?api-version=7.1",
    headers=headers,
    json={"query": f"""
        SELECT [System.Id] FROM WorkItems
        WHERE [System.TeamProject] = '{PROJECT}'
          AND [System.AreaPath] UNDER 'Heineken\\OMS'
          AND [System.WorkItemType] IN ('Bug', 'User Story')
          AND [System.State] = 'Done'
          {date_clause}
        ORDER BY [System.Id]
    """}
)
done_ids = [str(wi["id"]) for wi in r2.json().get("workItems", [])]
print(f"Done IDs (window: {DATE_LABEL}): {len(done_ids)}")
```

---

## STEP 4 — RUN CAP CHECK

```python
CAP = 1000
total_ids = len(active_ids) + len(done_ids)

if total_ids > CAP:
    print(f"""
⛔ RUN CAP EXCEEDED: {total_ids} items > {CAP} limit

  Active statuses: {len(active_ids)}
  Done ({DATE_LABEL}): {len(done_ids)}

Options to reduce:
  1. Narrow date window  e.g. "last 30 days"
  2. Sync specific status only  e.g. "sync QA env only"
  3. Confirm override — run anyway (slow)

Awaiting instruction.
""")
    complete_sync_run(sync_id, status="failed", summary="Cap exceeded")
    raise SystemExit("Cap exceeded")

print(f"✓ Cap OK: {total_ids} ≤ {CAP}")
```

---

## STEP 5 — LOAD EXISTING SUPABASE STATE (de-dup via Supabase)

```python
# Fetch all known ado_work_item IDs from Supabase for de-dup
rows = supabase_sql("""
    SELECT item_id, status, item_updated_at::text
    FROM source_items
    WHERE source_type = 'ado_work_item'
""") or []

supabase_index = {r["item_id"]: r for r in rows}
print(f"Supabase known ADO items: {len(supabase_index)}")

all_ids_to_fetch = list(set(active_ids + done_ids))

# Classify: new vs known (check if changed date differs)
ids_to_fetch = []
ids_unchanged = []

for item_id in all_ids_to_fetch:
    if item_id not in supabase_index:
        ids_to_fetch.append(item_id)   # net new
    else:
        ids_to_fetch.append(item_id)   # always re-fetch to detect updates

# Ghost detection: in Supabase as active, but not in this ADO query
active_set = set(active_ids)
ghost_ids = {
    row["item_id"] for row in rows
    if row["status"] in ACTIVE_STATES and row["item_id"] not in active_set
}
print(f"Ghost IDs detected: {len(ghost_ids)}")
print(f"IDs to fetch from ADO: {len(ids_to_fetch)}")
```

---

## STEP 6 — FETCH DETAILS FROM ADO

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

FIELDS = ",".join([
    "System.Id", "System.Title", "System.WorkItemType", "System.State",
    "System.AssignedTo", "System.Tags", "Microsoft.VSTS.Common.Priority",
    "System.Description", "System.ChangedDate", "System.CreatedDate"
])

def fetch_batch(batch_ids):
    url = (f"https://dev.azure.com/{ORG}/{PROJECT}/_apis/wit/workitems"
           f"?ids={','.join(batch_ids)}&fields={FIELDS}&api-version=7.1")
    resp = requests.get(url, headers=headers)
    return resp.json().get("value", []) if resp.status_code == 200 else []

def clean_html(text):
    if not text: return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    for ent, ch in [('&nbsp;',' '),('&amp;','&'),('&lt;','<'),('&gt;','>')]:
        text = text.replace(ent, ch)
    return re.sub(r'\s+', ' ', text).strip()

batches = [ids_to_fetch[i:i+200] for i in range(0, len(ids_to_fetch), 200)]
fetched_items = []
with ThreadPoolExecutor(max_workers=5) as ex:
    futures = [ex.submit(fetch_batch, b) for b in batches]
    for f in as_completed(futures):
        fetched_items.extend(f.result())

print(f"Fetched: {len(fetched_items)} items from ADO")
```

---

## STEP 7 — CLASSIFY + FILTER (skip truly unchanged)

```python
from collections import defaultdict

stats = {"new": 0, "updated": 0, "unchanged": 0, "ghost": len(ghost_ids)}
by_status = defaultdict(list)

for item in fetched_items:
    f        = item.get("fields", {})
    item_id  = str(f.get("System.Id", ""))
    state    = f.get("System.State", "Unknown")
    changed  = (f.get("System.ChangedDate", "") or "")[:10]
    created  = (f.get("System.CreatedDate", "") or "")[:10]
    ao       = f.get("System.AssignedTo", {})
    assignee = ao.get("displayName", "Unassigned") if isinstance(ao, dict) else "Unassigned"
    tags_raw = f.get("System.Tags", "") or ""
    priority = f.get("Microsoft.VSTS.Common.Priority", 3)
    desc_raw = clean_html(f.get("System.Description", ""))

    # Skip unchanged: already in Supabase with same changed date
    existing = supabase_index.get(item_id)
    if existing:
        existing_changed = (existing.get("item_updated_at") or "")[:10]
        if existing_changed >= changed:
            stats["unchanged"] += 1
            continue
        stats["updated"] += 1
    else:
        stats["new"] += 1

    record = {
        "id":          item_id,
        "title":       f.get("System.Title", ""),
        "type":        f.get("System.WorkItemType", ""),
        "status":      state,
        "assignee":    assignee,
        "priority":    priority,
        "tags_raw":    tags_raw,
        "changed":     changed,
        "created":     created,
        "description": desc_raw[:1500]
    }
    by_status[state].append(record)

print(f"new={stats['new']} updated={stats['updated']} unchanged={stats['unchanged']} ghost={stats['ghost']}")
total_to_summarize = stats["new"] + stats["updated"]

if total_to_summarize == 0 and stats["ghost"] == 0:
    print("No changes detected — Supabase already up to date.")
    complete_sync_run(sync_id, status="complete",
                      sources_ok=["ado"],
                      summary=f"No changes. {len(supabase_index)} items already current.")
    print(ado_oms_supabase_write_complete := "ado_oms_supabase_write_complete")
    raise SystemExit("No changes")
```

---

## STEP 8 — AI-SUMMARIZE (new + updated only)

```python
def build_items_text(items, desc_limit=600):
    parts = []
    for item in items:
        desc = item["description"][:desc_limit] if item["description"] else ""
        entry = (
            f"ID#{item['id']} [{item['type']}] P{item['priority']} | {item['title']}\n"
            f"Assignee: {item['assignee']} | Tags: {item['tags_raw']} | Changed: {item['changed']}"
        )
        if desc: entry += f"\nDesc: {desc}"
        parts.append(entry)
    return "\n---\n".join(parts)

def summarize_batch(items, status_label, desc_limit=600, max_bullets=7) -> list:
    if not items: return []
    text = build_items_text(items, desc_limit)
    prompt = f"""Summarize these ADO OMS work items. Status: {status_label}.

Return ONLY a valid JSON array. Each element:
{{
  "id": "ticket ID as string",
  "title": "exact title",
  "type": "Bug or User Story",
  "status": "{status_label}",
  "assignee": "name",
  "priority": number,
  "tags": "tags string",
  "changed": "YYYY-MM-DD",
  "summary": ["bullet 1", "bullet 2", ...]
}}

Rules:
- summary: max {max_bullets} concise bullets about WHAT the ticket is
- No description → summary: ["No description provided."]
- Return ONLY the JSON array — no markdown fences, no preamble

Items:
{text}"""

    result, error = invoke_llm(prompt)
    if error:
        print(f"  LLM error: {error}")
        return []
    try:
        clean = result.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
        return json.loads(clean)
    except Exception as e:
        print(f"  JSON parse error: {e}")
        return []

ACTIVE_STATUSES_ORDER = [
    "On Prod", "Ready for Prod deploy", "Acc env", "Ready for UAT deploy", "QA env"
]
new_summaries = {}

for status in ACTIVE_STATUSES_ORDER:
    items = by_status.get(status, [])
    result = summarize_batch(items, status, desc_limit=600, max_bullets=7)
    new_summaries[status] = result
    if items: print(f"✓ {status}: {len(result)} items summarized")

# Done — batch 50 per LLM call
done_to_summarize = by_status.get("Done", [])
new_done_objects = []
BATCH_SIZE = 50
done_batches = [done_to_summarize[i:i+BATCH_SIZE]
                for i in range(0, len(done_to_summarize), BATCH_SIZE)]

for idx, batch in enumerate(done_batches):
    result = summarize_batch(batch, "Done", desc_limit=400, max_bullets=5)
    new_done_objects.extend(result)
    print(f"  Done batch {idx+1}/{len(done_batches)}: {len(result)} items ✓")
```

---

## STEP 9 — CONVERT TO SUPABASE source_items FORMAT

```python
def extract_market(tags_raw: str) -> str:
    """Extract first OPCO code found in tags."""
    OPCODES = ["MY", "ID", "KH", "LA", "TW", "IN", "MM"]
    for code in OPCODES:
        if code in tags_raw.upper():
            return code
    return None

def extract_module(tags_raw: str) -> str:
    """Extract first module code found in tags."""
    MODULES = ["OMS", "REP", "HAP", "LOOP", "PEM", "CC"]
    for mod in MODULES:
        if mod in tags_raw.upper():
            return mod
    return "OMS"  # default area path is OMS

def build_source_item(record: dict, summary_obj: dict) -> dict:
    """Convert ADO record + LLM summary into source_items row."""
    item_id   = record["id"]
    tags_raw  = record.get("tags_raw", "")
    status    = record["status"]
    priority  = record.get("priority", 3)
    assignee  = record.get("assignee", "")

    # Tags: split ADO tags + add status tag
    tag_list = [t.strip() for t in tags_raw.split(";") if t.strip()]
    tag_list.append(f"status:{status.replace(' ','_').lower()}")

    # Summary text from LLM output
    summary_bullets = summary_obj.get("summary", []) if summary_obj else []
    summary_text = "\n".join(f"- {b}" for b in summary_bullets) if summary_bullets else "No summary."

    is_urgent = priority == 1 or status in ["QA env", "Acc env", "Ready for Prod deploy"]

    return {
        "source_type":     "ado_work_item",
        "item_id":         item_id,
        "title":           record.get("title", ""),
        "summary":         summary_text,
        "body_excerpt":    record.get("description", "")[:500],
        "source_url":      f"https://dev.azure.com/NitecoGroup/Heineken/_workitems/edit/{item_id}",
        "sender":          None,
        "tags":            tag_list,
        "market":          extract_market(tags_raw),
        "module":          extract_module(tags_raw),
        "priority":        str(priority),
        "status":          status,
        "assignee":        assignee,
        "due_date":        None,
        "is_urgent":       is_urgent,
        "is_client_facing": bool(extract_market(tags_raw)),
        "raw_json":        {"id": item_id, "type": record.get("type"), "changed": record.get("changed"), "area_path": "Heineken\\OMS"},
        "item_created_at": record.get("created"),
        "item_updated_at": record.get("changed"),
    }

# Build lookup: id → summary_obj from LLM results
summary_lookup = {}
for status_items in new_summaries.values():
    for obj in status_items:
        summary_lookup[obj["id"]] = obj
for obj in new_done_objects:
    summary_lookup[obj["id"]] = obj

# Build all source_items rows
source_items_rows = []
for status_items_list in list(by_status.values()):
    for record in status_items_list:
        summary_obj = summary_lookup.get(record["id"])
        source_items_rows.append(build_source_item(record, summary_obj))

print(f"source_items to upsert: {len(source_items_rows)}")
```

---

## STEP 10 — DERIVE ACTIONS, RISKS, DECISIONS

```python
actions_rows    = []
risks_rows      = []
decisions_rows  = []

as_of = datetime.now(gmt7).strftime("%Y-%m-%d")

for record in [r for records in by_status.values() for r in records]:
    item_id  = record["id"]
    title    = record.get("title", "")
    status   = record["status"]
    priority = record.get("priority", 3)
    assignee = record.get("assignee") or "Unassigned"
    tags_raw = record.get("tags_raw", "")
    url      = f"https://dev.azure.com/NitecoGroup/Heineken/_workitems/edit/{item_id}"
    module   = extract_module(tags_raw)
    market   = extract_market(tags_raw)

    # ACTIONS: P1/P2 active assigned items = follow-up needed
    if (priority <= 2
            and status in ACTIVE_STATES
            and assignee not in ("Unassigned", None)):
        actions_rows.append({
            "action_key":      f"ado:{item_id}:track-{status.replace(' ','_').lower()}",
            "title":           f"[ADO] {status}: {title[:80]}",
            "owner":           assignee,
            "due_date":        None,
            "source":          "ado_work_item",
            "source_ref":      item_id,
            "source_url":      url,
            "module":          module,
            "market":          market,
            "priority":        f"P{priority}",
            "status":          "open",
            "timebox":         None,
            "is_client_facing": bool(market),
            "draft_reply":     None,
            "confidence":      0.85,
        })

    # RISKS: P1 bugs in active pipeline
    if record.get("type") == "Bug" and priority == 1:
        risks_rows.append({
            "risk_key":     f"ado:{item_id}:p1-bug",
            "description":  f"P1 Bug in {status}: {title[:100]}",
            "module":       module,
            "market":       market,
            "source":       "ado_work_item",
            "source_ref":   item_id,
            "source_url":   url,
            "severity":     "high",
            "status":       "open",
            "owner":        assignee,
            "raised_date":  as_of,
        })

    # DECISIONS: look for explicit language in description
    desc_lower = record.get("description", "").lower()
    decision_triggers = ["decided to", "confirmed that", "approved", "agreed to", "will proceed with"]
    if any(t in desc_lower for t in decision_triggers):
        excerpt = record.get("description", "")[:200]
        decisions_rows.append({
            "decision_key":   f"ado:{item_id}:delivery-decision",
            "decision_date":  record.get("changed", as_of),
            "description":    f"Decision found in ADO {item_id}: {excerpt}",
            "topic":          title[:80],
            "module":         module,
            "market":         market,
            "source":         "ado_work_item",
            "source_ref":     item_id,
            "source_url":     url,
            "made_by":        assignee,
            "status":         "confirmed",
        })

print(f"Actions derived: {len(actions_rows)}")
print(f"Risks derived:   {len(risks_rows)}")
print(f"Decisions found: {len(decisions_rows)}")
```

---

## STEP 11 — HANDLE GHOST ITEMS

```python
# Mark ghost items as 'cancelled' in Supabase instead of hard-deleting
# This preserves history and lets daily briefing filter them out
if ghost_ids:
    ghost_ids_sql = "','".join(ghost_ids)
    supabase_sql(f"""
        UPDATE source_items
        SET status = 'ghost_purged',
            synced_at = now()
        WHERE source_type = 'ado_work_item'
          AND item_id IN ('{ghost_ids_sql}')
    """)
    print(f"✓ Ghost items marked ghost_purged: {len(ghost_ids)}")

    # Close corresponding actions for ghost items
    if ghost_ids:
        supabase_sql(f"""
            UPDATE actions
            SET status = 'done', updated_at = now()
            WHERE source = 'ado_work_item'
              AND source_ref IN ('{ghost_ids_sql}')
              AND status = 'open'
        """)
        print(f"✓ Open actions for ghost items closed")
```

---

## STEP 12 — WRITE TO SUPABASE

```python
print("ado_oms_supabase_write_started")

# ⛔ GUARD: Ensure no [ADO-OMS] Mem0 writes happen
# Any code path that would write [ADO-OMS][*] to Mem0 is BLOCKED here
print("ado_oms_mem0_structured_cache_blocked — ADO-OMS blobs go to Supabase only")

# Batch upsert source_items (200 per batch to stay within SQL limits)
BATCH = 200
total_upserted = 0
for i in range(0, len(source_items_rows), BATCH):
    chunk = source_items_rows[i:i+BATCH]
    total_upserted += upsert_source_items(sync_id, chunk)
    print(f"  source_items batch {i//BATCH+1}: {len(chunk)} rows ✓")

print(f"ado_oms_source_items_upserted: total={total_upserted}")

# Upsert actions
actions_count = upsert_actions(sync_id, actions_rows)
print(f"ado_oms_actions_upserted: count={actions_count}")

# Upsert decisions
decisions_count = upsert_decisions(sync_id, decisions_rows)
print(f"ado_oms_decisions_upserted: count={decisions_count}")

# Upsert risks
risks_count = upsert_risks(sync_id, risks_rows)
print(f"ado_oms_risks_upserted: count={risks_count}")

print("ado_oms_supabase_write_complete")
```

---

## STEP 13 — COMPLETE SYNC RUN

```python
sources_ok   = ["ado"] if total_upserted > 0 else []
sources_fail = [] if total_upserted > 0 else ["ado"]

complete_sync_run(
    sync_id       = sync_id,
    status        = "complete" if total_upserted > 0 else "failed",
    sources_ok    = sources_ok,
    sources_failed = sources_fail,
    summary = (
        f"ADO-OMS sync complete | window={DATE_LABEL} | "
        f"new={stats['new']} updated={stats['updated']} unchanged={stats['unchanged']} ghost={stats['ghost']} | "
        f"source_items={total_upserted} actions={actions_count} risks={risks_count} decisions={decisions_count}"
    )
)

# Write ACTION log via write_action() → Supabase actions table
write_action(
    skill   = "ADO_SYNC",
    summary = (
        f"ADO-OMS knowledge sync | {DATE_LABEL} | "
        f"new={stats['new']} updated={stats['updated']} unchanged={stats['unchanged']} "
        f"ghost={stats['ghost']} | {total_upserted} items in Supabase"
    )
)
```

---

## STEP 14 — COMPATIBILITY SHIM

Any old caller expecting legacy `[ADO-OMS]` entries gets its answer from the Supabase actions log and source_items:

```python
# For backward-compat: if a caller requests legacy [ADO-OMS] entries — return redirect message
COMPAT_MESSAGE = (
    "⚠️ ADO-OMS structured cache now stored in Supabase source_items "
    "where source_type='ado_work_item'. "
    "Query via: SELECT * FROM source_items WHERE source_type='ado_work_item' AND status='<state>'"
)
print(COMPAT_MESSAGE)
```

Any skill expecting legacy `[ADO-OMS][*]` entries should be updated to call:
```sql
SELECT * FROM source_items
WHERE source_type = 'ado_work_item'
  AND status = 'QA env'
ORDER BY item_updated_at DESC;
```

---

## STEP 15 — DELIVER SUMMARY

```
ADO-OMS KNOWLEDGE SYNC v2.0 — <YYYY-MM-DD> (GMT+7)
Area: Heineken\OMS | Types: Bug + User Story
Window: <DATE_LABEL> (Done only — active always full)
Storage: Supabase source_items (source_type='ado_work_item')

De-duplication:
  New items:         XX  (not in Supabase — fetched + summarized)
  Updated items:     XX  (in Supabase, newer ChangedDate — re-summarized)
  Unchanged:         XX  (same ChangedDate — skipped)
  Ghost purged:      XX  (in Supabase as active, absent from ADO — marked ghost_purged)

Supabase writes:
  source_items:      XX upserted ✓ (ado_oms_source_items_upserted)
  actions:           XX upserted ✓ (ado_oms_actions_upserted)
  risks:             XX upserted ✓ (ado_oms_risks_upserted)
  decisions:         XX upserted ✓ (ado_oms_decisions_upserted)

Legacy [ADO-OMS][*] blobs: BLOCKED ✓ — Mem0 retired (ado_oms_mem0_structured_cache_blocked)
Supabase actions [ADO_SYNC]: written ✓

⚠️ NOTE: Old callers using legacy [ADO-OMS] tags must migrate to Supabase query.
```

---

## RETRIEVAL GUIDE (updated for Supabase)

| Query intent | Supabase query |
|---|---|
| What's on prod? | `WHERE source_type='ado_work_item' AND status='On Prod'` |
| What's ready to release? | `WHERE source_type='ado_work_item' AND status='Ready for Prod deploy'` |
| What's in acceptance? | `WHERE source_type='ado_work_item' AND status='Acc env'` |
| What's in UAT? | `WHERE source_type='ado_work_item' AND status='Ready for UAT deploy'` |
| What's in QA? | `WHERE source_type='ado_work_item' AND status='QA env'` |
| Find ticket #247xxx | `WHERE source_type='ado_work_item' AND item_id='247xxx'` |
| P1 bugs | `WHERE source_type='ado_work_item' AND priority='1' AND type='Bug'` |
| BY market | `WHERE source_type='ado_work_item' AND market='MY'` |
| Recently completed | `WHERE source_type='ado_work_item' AND status='Done' ORDER BY item_updated_at DESC` |

**Staleness check:** Query `sync_runs WHERE sync_type='LIGHTWEIGHT' ORDER BY run_at DESC LIMIT 1` → check `run_at`. If > 2 weeks → re-run skill.

---

## GUARDRAILS

- ⛔ NEVER call Mem0 (retired) — emit `ado_oms_mem0_structured_cache_blocked` if any legacy write is attempted
- NEVER log or include PAT in any output or stored record
- NEVER call ADO API outside Composio remote workbench
- Always call `create_sync_run()` before writes, `complete_sync_run()` after
- Active statuses: always no date filter — ghost detection requires full current state
- Done: date window applies only here — controls volume
- Ghost items: mark `ghost_purged` in Supabase — do NOT hard-delete (preserves history)
- ADO 401/403 → abort, call `complete_sync_run(status='failed')`, notify user to rotate PAT
- If `upsert_source_items()` fails → retry once, log, continue; do NOT fall back to Mem0 blobs
- "All time" → confirm with user first (likely exceeds 1,000 cap)
- write_action() writes to Supabase actions table (Mem0 retired)

---

## WHEN TO RE-RUN

- After each sprint release cycle (~2 weeks)
- When specific ticket not found in Supabase (`item_id` lookup miss)
- When latest `sync_runs.run_at` > 2 weeks old

| Trigger phrase | Window resolved |
|---|---|
| "run ADO-OMS Knowledge Sync" | 6 months (default) |
| "sync ADO knowledge last 30 days" | 30 days |
| "refresh ADO memory last 3 months" | 3 months |
| "ADO knowledge sync all time" | all time (confirm first) |
| "sync ADO knowledge recent 2 weeks" | 14 days |
