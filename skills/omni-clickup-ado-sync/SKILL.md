---
name: omni-clickup-ado-sync
description: "One-way sync ClickUp → Azure DevOps for OMNI program. v6.5: Non-destructive tag merge — STEP 7/8 EXISTING paths now ADD only missing tags (case-insensitive) instead of overwriting System.Tags with the sync-derived subset, which used to strip meaningful ADO tags (PROMO, v1.0, OMS) and re-case others every run. v6.4: ACTIVE_STATUSES gap fix — 'approved for dev' added + drop-logger surfaces any unlisted non-terminal status. v6.3: Live title fix — fetch live ClickUp name before CREATE; re-check WIQL with live title to avoid duplicates under stale Supabase names. v6.2: Status filter fix + title dedup (STEP 3B2 strips list-suffixes). v6.0: Supabase-only. Triggers on 'run ado sync', 'sync clickup to ado', 'clickup ado sync'."
---

# ClickUp → ADO Sync — v6.5

## ⚠️ READ FIRST — SHARED CONFIG + UTILS

**Before executing any step, read in this order:**
1. `/mnt/skills/user/omni-config/SKILL.md` → loads constants (CONFIG_VERSION = "1.8")
2. `/mnt/skills/user/omni-utils/SKILL.md` → loads utilities (UTILITY_VERSION = "11.1")

## ⛔ MEM0 IS RETIRED — v6.0

```
Mem0 skipped — Supabase is now the source of truth.
```

- Do NOT read ClickUp cache from Mem0
- Do NOT write `[ADO-SYNC]` timestamp to Mem0 — Mem0 is fully retired
- Timestamp is read from `sync_runs WHERE sync_type='ADO_SYNC'` (primary) or `actions` table (fallback). No Mem0 path.

---

## STEP 0 — CACHE CHECK (Supabase)

Query Supabase for the most recent completed sync run and the current context pack.

```python
# Check last ADO sync run
latest_ado_run = supabase_sql("""
    SELECT id, run_at, summary FROM sync_runs
    WHERE sync_type = 'ADO_SYNC' AND status = 'complete'
    ORDER BY run_at DESC LIMIT 1
""")

# Check ClickUp data freshness via latest data sync
latest_data_run = supabase_sql("""
    SELECT run_at FROM sync_runs
    WHERE sync_type IN ('FULL','LIGHTWEIGHT') AND status = 'complete'
    ORDER BY run_at DESC LIMIT 1
""")
```

| Condition | Action |
|---|---|
| `latest_data_run` exists AND < 12h old | Proceed — Supabase cache fresh |
| `latest_data_run` exists AND > 12h old | Proceed with warning: `⚠️ ClickUp cache is Xh old — ADO sync may miss recent updates.` |
| `latest_data_run` missing | Abort: `ClickUp cache missing. Run omni-data-sync first, then re-run ADO sync.` |

Load comment signals from Supabase for mismatch detection:
```python
# Load open comment signals for cross-reference
comment_signals = supabase_sql("""
    SELECT item_id, title, summary, tags, market, module, raw_json
    FROM source_items
    WHERE source_type = 'clickup_comment'
      AND reply_status = 'pending'
      AND synced_at >= now() - INTERVAL '7 days'
""") or []

# Index by task_id extracted from raw_json
cs_by_task = {}
for sig in comment_signals:
    rj = sig.get("raw_json") or {}
    task_id = rj.get("task_id") or ""
    if task_id:
        cs_by_task.setdefault(task_id, []).append({
            "signal_type": rj.get("signal_type",""),
            "summary":     sig.get("summary",""),
            "task_id":     task_id,
        })

print(f"Comment signals loaded: {sum(len(v) for v in cs_by_task.values())} across {len(cs_by_task)} tasks")
```

---

## STEP 1 — LOAD ADO PAT

Read PAT from `/mnt/project/ado_pat.txt`. Trim whitespace.
**NEVER print, log, or include the PAT anywhere in output.**
If missing or empty → abort with error, no HTTP calls made.

```python
with open("/mnt/project/ado_pat.txt") as f:
    PAT = f.read().strip()
if not PAT:
    raise SystemExit("ADO PAT missing — aborting")
import base64
pat_b64 = base64.b64encode(f":{PAT}".encode()).decode()
```

---

## STEP 2 — LOAD LAST SYNC TIMESTAMP

Read last ADO sync timestamp from Supabase `sync_runs`:

```python
# Timestamp resolution priority:
# 1. sync_runs WHERE sync_type = 'ADO_SYNC'  → official (primary)
# 2. actions table fallback                  → compatibility for runs before DDL fix
# 3. None found                              → FULL MODE

last_run_ts = None

# Priority 1: sync_runs (canonical — now that ADO_SYNC is in constraint)
last_ado_run = supabase_sql("""
    SELECT run_at FROM sync_runs
    WHERE sync_type = 'ADO_SYNC' AND status = 'complete'
    ORDER BY run_at DESC LIMIT 1
""")

if last_ado_run:
    last_run_ts = last_ado_run[0]["run_at"]
    print(f"Mode: INCREMENTAL (since {last_run_ts}) [source: sync_runs]")
else:
    # Priority 2: actions table fallback (temporary compat for runs before DDL fix)
    fallback_row = supabase_sql("""
        SELECT created_at FROM actions
        WHERE source = 'omni-clickup-ado-sync'
          AND status = 'done'
          AND title ILIKE '%ADO sync%completed%'
        ORDER BY created_at DESC LIMIT 1
    """)
    if fallback_row:
        last_run_ts = fallback_row[0]["created_at"]
        print(f"Mode: INCREMENTAL (since {last_run_ts}) [source: actions fallback]")
    else:
        # Priority 3: no record found → FULL MODE
        print("Mode: FULL (no prior ADO sync record in sync_runs or actions)")
        last_run_ts = None
```

---

## STEP 3 — LOAD CLICKUP TASKS FROM SUPABASE

### 3A — Query active tasks updated since last sync

```python
# Build incremental filter
if last_run_ts:
    time_filter = f"AND item_updated_at > '{last_run_ts}'"
else:
    time_filter = ""  # FULL mode — all active tasks

tasks_raw = supabase_sql(f"""
    SELECT item_id, title, status, priority, module, market,
           source_tags, tags, source_url, item_updated_at, raw_json
    FROM source_items
    WHERE source_type = 'clickup_task'
      AND status NOT IN ('closed','done','complete','cancelled','released','completed','on hold')
      AND title NOT ILIKE '%OMNI - Design%'
      {time_filter}
    ORDER BY item_updated_at DESC
    LIMIT 100
""") or []

print(f"Tasks loaded from Supabase: {len(tasks_raw)}")
if len(tasks_raw) == 0 and last_run_ts:
    print("No ClickUp task changes since last ADO sync — nothing to do.")
    # Still run STEP 10 to record timestamp
```

### 3B — Apply status filter + PROMO mapping

```python
# ACTIVE_STATUSES: all statuses that should be synced to ADO.
# NOTE: "open" is intentionally in ACTIVE_STATUSES only. Do NOT add it to any skip set.
# v6.4: "approved for dev" added — it was silently dropped (passed the SQL
# terminal-status blacklist but was missing from this whitelist).
ACTIVE_STATUSES = {
    "open",
    "backlog",
    "in progress",
    "approved & to be evaluated",
    "approved for dev",
    "dev in progress",
    "to do",
    "acc environment",
    "qa environment",
    "active",
    "in review",
    "ui design",
    "carpark",
}

# TERMINAL_STATUSES: closed/closed-equivalent states. These are already excluded
# by the SQL query in STEP 3A; listed here so the drop-logger below does NOT warn
# about them. 'rejected' belongs here (it is NOT in the SQL blacklist, so the
# whitelist is what keeps it out — keep it out of ACTIVE_STATUSES).
TERMINAL_STATUSES = {
    "closed", "done", "complete", "completed", "cancelled",
    "released", "on hold", "rejected", "archived",
}

# SKIP_STATUSES: EMPTY — all non-terminal statuses must sync to ADO.
# ui design, carpark, in review are valid work states and must be included.
# The only exclusion is titles matching 'OMNI - Design'.
SKIP_STATUSES = set()  # intentionally empty — do NOT add statuses here

tasks_to_sync = []
skipped_count = 0
unlisted_active = {}   # status -> count, for observability (see drop-logger)
for t in tasks_raw:
    # Always normalize: strip whitespace + lowercase before any comparison.
    # This handles "Open", "OPEN", " open " → "open" correctly.
    status = (t.get("status") or "").strip().lower()
    title  = t.get("title","")
    if status not in ACTIVE_STATUSES:
        # v6.4 drop-logger: a non-terminal status that is not whitelisted is a
        # potential gap (this is exactly what silently dropped 'approved for dev').
        # Surface it loudly so the whitelist can be extended on the next run
        # instead of failing silently.
        if status and status not in TERMINAL_STATUSES:
            unlisted_active[status] = unlisted_active.get(status, 0) + 1
        skipped_count += 1; continue
    if "omni - design" in title.lower():
        skipped_count += 1; continue
    # Derive PROMO flag from module
    t["_is_promo"] = t.get("module","").upper() in ("PEM","PROMO","TPM")
    tasks_to_sync.append(t)

print(f"Tasks after filter: {len(tasks_to_sync)} active | {skipped_count} skipped (status/design)")
if unlisted_active:
    print(f"⚠️ UNLISTED non-terminal statuses dropped — review and add to ACTIVE_STATUSES: {unlisted_active}")
```

### 3B2 — Title deduplication (MANDATORY)

ClickUp tasks often exist in multiple lists (e.g. "PROMO" and "REP MANAGER - 1") with near-identical titles where one has a list-suffix like `(REP MGR-1)`, `(PROMO)`, `(PROMO list)`. Without deduplication, both versions sync to ADO creating duplicates.

**Rule:** If a task title, after stripping known list-suffixes, matches another task's title → keep only ONE. Prefer the task with the **canonical title** (no suffix). If both have suffixes, keep the one with the lower item_id (oldest).

```python
import re

LIST_SUFFIXES = [
    r'\s*\(REP MGR-1\)\s*$',
    r'\s*\(PROMO\)\s*$',
    r'\s*\(PROMO list\)\s*$',
    r'\s*\(REP MGR-2\)\s*$',
]

def normalize_title(title: str) -> str:
    """Strip known list-suffixes to get canonical base title."""
    t = title.strip()
    for pattern in LIST_SUFFIXES:
        t = re.sub(pattern, '', t, flags=re.IGNORECASE).strip()
    return t

# Build a deduplicated list — one item per canonical title
seen_base_titles = {}   # base_title → task dict (winner)
deduped = []
dupe_count = 0

for t in tasks_to_sync:
    title = t.get("title", "")
    base  = normalize_title(title)
    is_suffixed = (base != title.strip())

    if base not in seen_base_titles:
        seen_base_titles[base] = t
        deduped.append(t)
    else:
        existing = seen_base_titles[base]
        existing_is_suffixed = (normalize_title(existing["title"]) != existing["title"].strip())

        # Replace existing with this one if: this has no suffix but existing does
        if not is_suffixed and existing_is_suffixed:
            deduped.remove(existing)
            seen_base_titles[base] = t
            deduped.append(t)
            print(f"  [DEDUP] Replaced '{existing['title'][:50]}' with canonical '{title[:50]}'")
        else:
            print(f"  [DEDUP] Skipped '{title[:50]}' (dupe of '{existing['title'][:50]}')")
        dupe_count += 1

tasks_to_sync = deduped
print(f"After dedup: {len(tasks_to_sync)} unique | {dupe_count} duplicates removed")
```

### 3C — Separate parents and subtasks

```python
# Subtasks have a parent_id in raw_json
parent_tasks = []
subtasks     = []
for t in tasks_to_sync:
    rj = t.get("raw_json") or {}
    if rj.get("parent"):
        t["_cu_parent_id"] = rj["parent"]
        subtasks.append(t)
    else:
        parent_tasks.append(t)

print(f"Parents: {len(parent_tasks)} | Subtasks: {len(subtasks)}")
```

### 3D — CAP check

```python
if len(parent_tasks) > 50 and not last_run_ts:
    print(f"⚠️ CAP: {len(parent_tasks)} new items in FULL mode — capping at 50. Run incremental syncs to catch up.")
    parent_tasks = parent_tasks[:50]
```

---

## STEP 3E — fetch_full_description (MANDATORY FOR EVERY NEW ITEM)

⛔ **THIS STEP IS NON-NEGOTIABLE. NEVER SKIP. NEVER SUBSTITUTE A PLACEHOLDER.**

`fetch_full_description()` MUST be called for every item where ADO does not yet exist (new items).
It is also called for existing items where ADO description is currently blank (backfill).

Calling pattern:
- New item → always call before CREATE
- Existing item with blank ADO description → call before UPDATE
- Existing item with populated ADO description → skip (no re-fetch needed unless description changed upstream)

```python
def fetch_full_description(task_id: str, task_name: str = "") -> tuple[str, list]:
    """
    Fetch live description + attachments from ClickUp via MCP.
    Returns (desc_text, attachments_list).
    Retries once on failure.
    Returns ("", []) on both failures — caller MUST write empty description, NOT a placeholder URL.

    CRITICAL CONTRACT:
    - Empty return → write empty ADO description. NEVER substitute a ClickUp URL.
    - The ClickUp URL is already in the ADO work item's title link. A URL-only description
      is noise and creates confusion. Empty is always correct.
    - Never skip this call for new items. "Saving time" is not a valid reason to skip.
    """
    for attempt in range(1, 3):
        try:
            result = ClickUp.clickup_get_task(task_id=task_id, detail_level="detailed")
            if not result:
                raise ValueError("empty response")
            desc = (result.get("description") or result.get("text_content") or "").strip()
            atts = result.get("attachments") or []
            print(f"  [3E] OK attempt={attempt}: '{task_name[:40]}' desc={len(desc)}c atts={len(atts)}")
            return desc, atts
        except Exception as e:
            print(f"  [3E] WARN attempt={attempt} failed for '{task_name[:40]}': {e}")
            if attempt < 2:
                import time; time.sleep(0.5)

    print(f"  [3E] WARN both attempts failed for '{task_name[:40]}' — writing empty description ⚠️")
    return "", []
```

**Apply in the main loop (STEP 7):**

```python
# For NEW items:
desc_text, attachments = fetch_full_description(task["item_id"], task["title"])
task["_full_md"]      = desc_text
task["_attachments"]  = attachments

# For EXISTING items with blank ADO description:
if not cur_ado_desc.strip():
    desc_text, _ = fetch_full_description(task["item_id"], task["title"])
    task["_full_md"] = desc_text
```

⛔ **FORBIDDEN:**
```python
desc_html = ""  # ← FORBIDDEN in CREATE path — always call fetch_full_description() first
desc_html = f"<p>ClickUp: <a href='...'>...</a></p>"  # ← FORBIDDEN placeholder
```

---

## STEP 3F — Comment Signal Cross-Reference

Check each task against `cs_by_task` for ADO-relevant mismatches. Non-blocking.

```python
ado_mismatches = []

for task in tasks_to_sync:
    task_id   = task.get("item_id","")
    task_sigs = cs_by_task.get(task_id, [])
    if not task_sigs: continue

    cu_status   = (task.get("status") or "").lower()
    cu_priority = (task.get("priority") or "").lower()

    for sig in task_sigs:
        signal_type = sig.get("signal_type","")
        mismatch    = None

        if signal_type == "BLOCKER" and cu_status not in ("blocked","closed","done","complete"):
            mismatch = {
                "task_id": task_id, "task_name": task.get("title",""),
                "type": "BLOCKER_NOT_REFLECTED",
                "detail": f"Comment says blocked but ClickUp status is '{cu_status}'",
                "suggestion": "Update ClickUp status to Blocked; ensure ADO reflects this",
                "comment_summary": sig.get("summary",""),
            }
        elif signal_type in ("REQUIREMENT_CHANGE","SCOPE_RISK"):
            mismatch = {
                "task_id": task_id, "task_name": task.get("title",""),
                "type": "SCOPE_NOT_IN_DESCRIPTION",
                "detail": "Comment adds new scope/requirement not in task description",
                "suggestion": "Update ClickUp description and ADO work item",
                "comment_summary": sig.get("summary",""),
            }
        elif signal_type == "PRIORITY_CHANGE" and cu_priority in ("normal","low",""):
            mismatch = {
                "task_id": task_id, "task_name": task.get("title",""),
                "type": "PRIORITY_MISMATCH",
                "detail": f"Comment signals urgency but ClickUp priority is '{cu_priority}'",
                "suggestion": "Raise priority in ClickUp and ADO",
                "comment_summary": sig.get("summary",""),
            }
        elif signal_type == "STATUS_MISMATCH":
            mismatch = {
                "task_id": task_id, "task_name": task.get("title",""),
                "type": "CLOSURE_MISMATCH",
                "detail": sig.get("summary","Comment reports issue on closed/done task"),
                "suggestion": "Reopen task and verify issue in UAT/Prod",
                "comment_summary": sig.get("summary",""),
            }

        if mismatch:
            ado_mismatches.append(mismatch)

print(f"ADO/comment mismatches detected: {len(ado_mismatches)}")
```

---

## STEP 4 — ADO PROJECT MAPPING

```python
def get_project(task):
    return PROMO_PROJECT if task.get("_is_promo") else OMS_PROJECT

def get_work_type(task):
    return "Product Backlog Item" if task.get("_is_promo") else "User Story"

OMS_PROJECT   = "Heineken"
PROMO_PROJECT = "Heineken.0K9.TPM-POC"
```

---

## STEP 5 — ADO TAG RESOLUTION

⚠️ **ALWAYS use `source_tags` (original ClickUp tags). NEVER use `tags` (internal operator tags).**

```python
INTERNAL_TAG_PREFIXES = [
    "MODULE:", "OPCO:", "PRIORITY:", "MARKET:", "INTERNAL:",
    "OVERDUE", "DUE_TODAY", "URGENT", "BLOCKED", "DEPLOY",
]

def is_internal_tag(t: str) -> bool:
    return any(t.upper().startswith(p) or t.upper() == p for p in INTERNAL_TAG_PREFIXES)

def resolve_ado_tags(task: dict) -> str:
    """
    Returns ADO tags string: source_tags (original ClickUp) + module, joined with "; "
    Falls back to live ClickUp fetch if source_tags missing.
    """
    source_tags = task.get("source_tags") or []
    clean = [t for t in source_tags if not is_internal_tag(t)]

    rejected = [t for t in source_tags if is_internal_tag(t)]
    if rejected:
        print(f"  [WARN] internal_tags_rejected for ADO: task={task.get('item_id')} rejected={rejected}")

    if not clean:
        # Live ClickUp fallback
        cu_id = task.get("item_id","")
        if cu_id:
            try:
                live = ClickUp.clickup_get_task(task_id=cu_id, detail_level="summary")
                live_tags = [t["name"] for t in (live.get("tags") or []) if isinstance(t, dict) and t.get("name")]
                clean = [t for t in live_tags if not is_internal_tag(t)]
                if clean:
                    print(f"  [INFO] live_tag_fallback_used: task={cu_id} tags={clean}")
            except Exception as e:
                print(f"  [WARN] live tag fetch failed for {cu_id}: {e}")

    if not clean:
        print(f"  [WARN] tag_source_missing: task={task.get('item_id')} — no source tags")

    module = task.get("module","")
    all_tags = list(clean)
    if module and module not in all_tags:
        all_tags.append(module)

    return "; ".join(all_tags)


def merge_ado_tags(cur_tags: str, new_tags_str: str) -> str | None:
    """
    Non-destructive ADDITIVE tag merge (v6.5).
    Returns a merged tag string ONLY if the sync-derived tags add something not
    already present on the ADO item (case-insensitive). Returns None when no
    addition is needed → no update → zero churn.

    ⚠️ This REPLACES the old exact-overwrite behaviour which was destructive:
       it stripped meaningful existing ADO tags (e.g. 'PROMO', 'RejectedClaim',
       version tags like 'v1.0', area tags like 'OMS') and re-cased others
       (KH → kh) on every run. Overwriting with a subset effectively DELETES
       tags, violating the 'NEVER delete' guardrail.

    Rules:
    - Keep ALL existing ADO tags exactly as-is (original casing, order).
    - Append only sync-derived tags whose lowercase form is not already present.
    - Case-insensitive dedup so 'KH' already covers a derived 'kh'.
    """
    cur = [t.strip() for t in (cur_tags or "").split(";") if t.strip()]
    new = [t.strip() for t in (new_tags_str or "").split(";") if t.strip()]
    cur_lower = {t.lower() for t in cur}
    additions = [t for t in new if t.lower() not in cur_lower]
    return "; ".join(cur + additions) if additions else None
```

---

## STEP 6 — MATCH TASKS TO ADO (per-title WIQL)

```python
import requests, time

ADO_BASE = "https://dev.azure.com/NitecoGroup"
ADO_H    = {"Content-Type": "application/json",            "Authorization": f"Basic {pat_b64}"}
ADO_HP   = {"Content-Type": "application/json-patch+json", "Authorization": f"Basic {pat_b64}"}
ADO_HU   = {"Content-Type": "application/octet-stream",    "Authorization": f"Basic {pat_b64}"}

def wiql_find(project: str, title: str) -> int | None:
    t_esc = title.replace("'", "''")
    body  = {"query": f"SELECT [System.Id] FROM WorkItems WHERE [System.Title] = '{t_esc}' AND [System.TeamProject] = '{project}'"}
    r = requests.post(f"{ADO_BASE}/{project}/_apis/wit/wiql?api-version=7.1",
        json=body, headers=ADO_H, timeout=15)
    if r.status_code == 401: raise Exception("AUTH_FAILED — rotate PAT")
    if r.status_code != 200: return None
    items = r.json().get("workItems", [])
    return items[0]["id"] if items else None

def get_ado_item(project: str, ado_id: int) -> dict | None:
    r = requests.get(f"{ADO_BASE}/{project}/_apis/wit/workitems/{ado_id}?api-version=7.1",
        headers=ADO_H, timeout=15)
    return r.json() if r.status_code == 200 else None
```

---

## STEP 7 — SYNC PARENTS → ADO USER STORIES / PBIs

### Description converter

```python
import re, html as html_mod

def markdown_to_ado_html(md: str) -> str:
    """
    Four-pass markdown → ADO HTML converter.
    Source MUST be task["_full_md"] set by fetch_full_description() in STEP 3E.
    Returns "" for empty input — never returns a placeholder.
    """
    if not md or not md.strip():
        return ""

    # PASS 0 — strip base64 embeds, external image embeds, ClickUp table-embed syntax
    md = re.sub(r'data:image/[A-Za-z0-9+/;=\r\n\s]+', 'BASE64_IMG_REMOVED', md, flags=re.DOTALL)
    md = re.sub(r'!\[[^\]]*\]\(\s*BASE64_IMG_REMOVED\s*\)', '[image attached]', md)
    md = re.sub(r'!\[[^\]]*\]\(\s*BASE64_IMG_REMOVED.*', '[image attached]', md, flags=re.DOTALL)
    md = md.replace('BASE64_IMG_REMOVED', '[image attached]')
    md = re.sub(r'^[A-Za-z0-9+/=]{100,}$', '', md, flags=re.MULTILINE)
    md = re.sub(r'!\[[^\]]*\]\(https?://[^)]+\)', '[image attached]', md)
    md = re.sub(r'\\---\s*\[image attached\]', '', md)
    md = re.sub(r'\\---\s*$', '', md, flags=re.MULTILINE)
    md = re.sub(r'\[table-embed:[^\]]+\]', '[table — see ClickUp]', md)

    # PASS 1 — markdown tables → placeholders
    tables = []
    def extract_md_table(match):
        rows = [r.strip() for r in match.group(0).strip().split("\n") if r.strip()]
        data_rows = [r for r in rows if not re.match(r'^[\|\-\s:]+$', r)]
        if not data_rows: return match.group(0)
        html_rows = []
        for i, row in enumerate(data_rows):
            cells = [c.strip() for c in row.strip("|").split("|")]
            tag   = "th" if i == 0 else "td"
            cols  = "".join(f"<{tag} style='padding:4px;border:1px solid #ccc'>{html_mod.escape(c)}</{tag}>" for c in cells)
            html_rows.append(f"<tr>{cols}</tr>")
        tbl = '<table style="border-collapse:collapse;margin:8px 0">' + "".join(html_rows) + "</table>"
        idx = len(tables); tables.append(tbl)
        return f"\x00TABLE{idx}\x00"
    md_proc = re.sub(r'(?:^\|.+\n)+(?:^\|[\|\-\:\s]+\n)(?:^\|.+\n?)+', extract_md_table, md, flags=re.MULTILINE)

    def apply_inline(text: str) -> str:
        text = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)',
            lambda m: f'<a href="{html_mod.escape(m.group(2))}">{m.group(1)}</a>', text)
        text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'\*(.+?)\*',     r'<em>\1</em>',         text)
        return text

    # PASS 2 — tokenise lines
    tokens = []
    for line in md_proc.split("\n"):
        s = line.strip()
        if not s: continue
        if re.match(r'^\x00TABLE\d+\x00$', s):
            tokens.append(("block", tables[int(re.search(r'\d+', s).group())])); continue
        bm = re.match(r'^(?:\*|-)\s+(.*)', s)
        if bm:
            tokens.append(("li",  apply_inline(html_mod.escape(bm.group(1).strip())))); continue
        nm = re.match(r'^(\d+)\\?\.\s+(.*)', s)
        if nm:
            tokens.append(("oli", apply_inline(html_mod.escape(nm.group(2).strip())))); continue
        if   s.startswith("### "): tokens.append(("block", f"<h3>{html_mod.escape(s[4:])}</h3>"))
        elif s.startswith("## "):  tokens.append(("block", f"<h2>{html_mod.escape(s[3:])}</h2>"))
        elif s.startswith("# "):   tokens.append(("block", f"<h1>{html_mod.escape(s[2:])}</h1>"))
        else:
            if len(s) > 200 and re.match(r'^[A-Za-z0-9+/=\(\)]+$', s): continue
            tokens.append(("block", f"<p>{apply_inline(html_mod.escape(s))}</p>"))

    # PASS 3 — group li/oli into ul/ol
    html_parts, i = [], 0
    while i < len(tokens):
        kind, content = tokens[i]
        if kind == "li":
            items = []
            while i < len(tokens) and tokens[i][0] == "li":
                items.append(f"<li>{tokens[i][1]}</li>"); i += 1
            html_parts.append("<ul>" + "".join(items) + "</ul>")
        elif kind == "oli":
            items = []
            while i < len(tokens) and tokens[i][0] == "oli":
                items.append(f"<li>{tokens[i][1]}</li>"); i += 1
            html_parts.append("<ol>" + "".join(items) + "</ol>")
        else:
            html_parts.append(content); i += 1
    return "\n".join(html_parts)
```

### Priority mapping

```python
def priority_to_ado(p) -> int:
    if not p: return 2
    return {"urgent":1,"high":2,"normal":3,"low":4,"p1":1,"p2":2,"p3":3}.get(str(p).lower(), 2)
```

### CREATE helper

```python
def create_ado_item(project, work_type, title, tags, priority, desc_html, is_promo=False) -> int | None:
    url  = f"{ADO_BASE}/{project}/_apis/wit/workitems/${requests.utils.quote(work_type)}?api-version=7.1"
    body = [
        {"op":"add","path":"/fields/System.Title",                   "value": title},
        {"op":"add","path":"/fields/Microsoft.VSTS.Common.Priority", "value": priority},
    ]
    if tags:      body.append({"op":"add","path":"/fields/System.Tags",        "value": tags})
    if desc_html: body.append({"op":"add","path":"/fields/System.Description", "value": desc_html})
    if not is_promo:
        body.append({"op":"add","path":"/fields/System.AreaPath",     "value": r"Heineken\OMS"})
        body.append({"op":"add","path":"/fields/System.IterationPath","value": r"Heineken\OMS\Kanban"})
    r = requests.post(url, json=body, headers=ADO_HP, timeout=15)
    return r.json().get("id") if r.status_code in (200, 201) else None
```

### UPDATE helper

```python
def update_ado_item(project, ado_id, changes: dict) -> bool:
    if not changes: return True
    body = [{"op":"replace","path":f"/fields/{k}","value":v} for k,v in changes.items()]
    r = requests.patch(f"{ADO_BASE}/{project}/_apis/wit/workitems/{ado_id}?api-version=7.1",
        json=body, headers=ADO_HP, timeout=15)
    return r.status_code == 200
```

### Main sync loop

```python
results = {"created":[], "updated":[], "unchanged":[], "errors":[],
           "att_added":0, "att_skipped":0, "att_errors":0}

new_item_count = 0  # for CAP check

for task in parent_tasks:
    title     = task["title"]
    is_promo  = task.get("_is_promo", False)
    project   = get_project(task)
    work_type = get_work_type(task)
    tags_str  = resolve_ado_tags(task)
    priority  = priority_to_ado(task.get("priority"))

    try:
        ado_id = wiql_find(project, title)
        time.sleep(0.15)

        if ado_id is None:
            # ── NEW ITEM ────────────────────────────────────────────────────
            # STEP 3E: fetch_full_description is MANDATORY. Never skip.
            print(f"  NEW — fetching description: {title[:55]}")
            cu_task_live = ClickUp.clickup_get_task(task_id=task["item_id"], detail_level="detailed")
            time.sleep(0.15)

            # ⚠️ ALWAYS use live ClickUp name as ADO title — Supabase cache may be stale/truncated
            if cu_task_live and cu_task_live.get("name"):
                live_title = cu_task_live["name"].strip()
                if live_title != title:
                    print(f"  [TITLE FIX] Supabase='{title[:40]}' → ClickUp='{live_title[:40]}'")
                    # Re-check WIQL with live title in case it already exists under that name
                    ado_id_live = wiql_find(project, live_title)
                    time.sleep(0.15)
                    if ado_id_live:
                        print(f"  [TITLE FIX] Found existing ADO #{ado_id_live} under live title — treating as UPDATE")
                        ado_id = ado_id_live
                        title  = live_title
                        # Fall through to UPDATE path below
                    else:
                        title = live_title  # use live title for CREATE
                desc_text  = (cu_task_live.get("description") or cu_task_live.get("text_content") or "").strip()
                attachments = cu_task_live.get("attachments") or []
            else:
                desc_text, attachments = fetch_full_description(task["item_id"], title)

            task["_full_md"]     = desc_text
            task["_attachments"] = attachments
            desc_html = markdown_to_ado_html(task["_full_md"])
            # desc_html may be "" if ClickUp task has no description — that is correct

            # Re-check ado_id — may have been updated by TITLE FIX above
            if ado_id is not None:
                # Redirect to update path
                existing = get_ado_item(project, ado_id)
                time.sleep(0.15)
                if existing:
                    cur_desc = (existing.get("fields",{}).get("System.Description","") or "").strip()
                    changes = {}
                    if not cur_desc and desc_html:
                        changes["System.Description"] = desc_html
                    if changes:
                        update_ado_item(project, ado_id, changes)
                        results["updated"].append({"title": title[:60], "ado_id": ado_id, "changed": list(changes.keys())})
                        print(f"  UPDATED (title-fix): #{ado_id} — {title[:55]}")
                    else:
                        results["unchanged"].append(title[:60])
                continue  # skip CREATE block

            new_item_count += 1
            if new_item_count > 50:
                print(f"⚠️ CAP REACHED: >50 new items — aborting to prevent runaway creation")
                results["errors"].append({"title": title[:60], "reason": "CAP >50 new items — run aborted"})
                break

            new_id = create_ado_item(project, work_type, title, tags_str, priority, desc_html, is_promo)
            time.sleep(0.15)

            if new_id:
                att_r = sync_attachments(new_id, task["_attachments"], project, pat_b64)
                results["att_added"]   += len(att_r["added"])
                results["att_skipped"] += len(att_r["skipped"])
                results["att_errors"]  += len(att_r["errors"])
                if att_r["added"] or att_r["errors"]:
                    print(f"    attachments: +{len(att_r['added'])} added, {len(att_r['skipped'])} skipped, {len(att_r['errors'])} errors")
                results["created"].append({
                    "title": title[:60], "ado_id": new_id, "project": project,
                    "desc_chars": len(desc_text), "attachments": att_r["added"],
                })
                print(f"  CREATED: #{new_id} — {title[:55]}")
            else:
                results["errors"].append({"title": title[:60], "reason": "create API failed"})
                print(f"  ERROR CREATE: {title[:60]}")

        else:
            # ── EXISTING ITEM ───────────────────────────────────────────────
            existing = get_ado_item(project, ado_id)
            time.sleep(0.15)
            if not existing:
                results["errors"].append({"title": title[:60], "reason": f"fetch ADO #{ado_id} failed"})
                continue

            fields       = existing.get("fields", {})
            cur_priority = fields.get("Microsoft.VSTS.Common.Priority")
            cur_tags     = fields.get("System.Tags", "") or ""
            cur_desc     = fields.get("System.Description", "") or ""

            changes = {}
            if cur_priority != priority:
                changes["Microsoft.VSTS.Common.Priority"] = priority
            if tags_str:
                merged_tags = merge_ado_tags(cur_tags, tags_str)  # additive, non-destructive (v6.5)
                if merged_tags:
                    changes["System.Tags"] = merged_tags

            # Empty-desc backfill: if ADO description is blank, fetch and patch
            if not cur_desc.strip():
                print(f"  EMPTY DESC backfill — fetching: {title[:55]}")
                desc_text, _ = fetch_full_description(task["item_id"], title)
                task["_full_md"] = desc_text
                desc_html = markdown_to_ado_html(desc_text)
                if desc_html:
                    changes["System.Description"] = desc_html

            if changes:
                ok = update_ado_item(project, ado_id, changes)
                time.sleep(0.15)
                if ok:
                    results["updated"].append({"title": title[:60], "ado_id": ado_id, "changed": list(changes.keys())})
                    print(f"  UPDATED: #{ado_id} — {title[:55]} {list(changes.keys())}")
                else:
                    results["errors"].append({"title": title[:60], "reason": f"update #{ado_id} failed"})
                    print(f"  ERROR UPDATE: #{ado_id} — {title[:55]}")
            else:
                results["unchanged"].append(title[:60])
                print(f"  UNCHANGED: #{ado_id} — {title[:55]}")

    except Exception as e:
        err = str(e)
        if "AUTH_FAILED" in err:
            print(f"AUTH_FAILED — aborting entire run"); break
        results["errors"].append({"title": title[:60], "reason": err})
        print(f"  ERROR: {title[:60]} — {err}")
```

---

## STEP 7A — SYNC ATTACHMENTS → ADO

Called after every successful CREATE (and UPDATE if new attachments found).

```python
def sync_attachments(ado_id: int, attachments: list, project: str, pat_b64: str) -> dict:
    """
    Download ClickUp attachments and upload to ADO work item.
    Deduplicates by filename (case-insensitive) against existing ADO relations.
    Returns {"added": [...], "skipped": [...], "errors": [...]}
    Errors are non-fatal — log and continue.
    """
    if not attachments:
        return {"added":[], "skipped":[], "errors":[]}

    # Fetch existing attachment names for dedup
    r = requests.get(f"{ADO_BASE}/{project}/_apis/wit/workitems/{ado_id}?$expand=relations&api-version=7.1",
        headers=ADO_H, timeout=15)
    existing_names = set()
    if r.status_code == 200:
        for rel in r.json().get("relations", []):
            if rel.get("rel") == "AttachedFile":
                existing_names.add(rel["attributes"].get("name","").lower())

    added, skipped, errors = [], [], []

    for att in attachments:
        name = (att.get("title") or att.get("name") or "attachment").replace(" ", "_")
        url  = att.get("url") or att.get("url_w_query") or att.get("url_w_host")

        if not url:           errors.append(f"{name}: no URL"); continue
        if name.lower() in existing_names: skipped.append(name); continue

        dl = requests.get(url, timeout=60)
        if dl.status_code != 200:
            errors.append(f"{name}: download HTTP {dl.status_code}"); continue

        up = requests.post(
            f"{ADO_BASE}/{project}/_apis/wit/attachments?fileName={requests.utils.quote(name)}&api-version=7.1",
            data=dl.content, headers=ADO_HU, timeout=60)
        if up.status_code not in (200, 201):
            errors.append(f"{name}: upload HTTP {up.status_code}"); continue

        lk = requests.patch(
            f"{ADO_BASE}/{project}/_apis/wit/workitems/{ado_id}?api-version=7.1",
            json=[{"op":"add","path":"/relations/-","value":{
                "rel": "AttachedFile",
                "url": up.json().get("url"),
                "attributes": {"comment": f"Synced from ClickUp — {name}"}
            }}],
            headers=ADO_HP, timeout=15)
        if lk.status_code == 200: added.append(name)
        else: errors.append(f"{name}: link HTTP {lk.status_code}")

    return {"added": added, "skipped": skipped, "errors": errors}
```

---

## STEP 8 — SYNC SUBTASKS → ADO TASKS

```python
# Build parent_id map from Step 7 results
parent_ado_map = {r["title"]: r["ado_id"] for r in results["created"]}
# Supplement with WIQL lookups for parents already in ADO
for task in subtasks:
    parent_cu_id = task.get("_cu_parent_id","")
    # Find parent title from tasks_raw
    parent_task = next((t for t in tasks_raw if t["item_id"] == parent_cu_id), None)
    if not parent_task:
        print(f"  SKIP subtask (parent not found): {task['title'][:50]}"); continue

    parent_title  = parent_task["title"]
    parent_is_promo = parent_task.get("_is_promo", False)
    project = get_project(parent_task)

    ado_parent_id = parent_ado_map.get(parent_title)
    if not ado_parent_id:
        ado_parent_id = wiql_find(project, parent_title)
        time.sleep(0.15)
    if not ado_parent_id:
        results["errors"].append({"title": task["title"][:60], "reason": "parent ADO id unresolvable"})
        print(f"  ERROR subtask (parent ADO not found): {task['title'][:50]}"); continue

    tags_str  = resolve_ado_tags(task)
    priority  = priority_to_ado(task.get("priority"))

    try:
        ado_id = wiql_find(project, task["title"])
        time.sleep(0.15)

        if ado_id is None:
            print(f"  NEW subtask — fetching description: {task['title'][:50]}")
            desc_text, attachments = fetch_full_description(task["item_id"], task["title"])
            desc_html = markdown_to_ado_html(desc_text)

            url  = f"{ADO_BASE}/{project}/_apis/wit/workitems/$Task?api-version=7.1"
            body = [
                {"op":"add","path":"/fields/System.Title",                   "value": task["title"]},
                {"op":"add","path":"/fields/Microsoft.VSTS.Common.Priority", "value": priority},
                {"op":"add","path":"/relations/-","value":{
                    "rel": "System.LinkTypes.Hierarchy-Reverse",
                    "url": f"{ADO_BASE}/{project}/_apis/wit/workitems/{ado_parent_id}",
                    "attributes": {"comment": "Synced from ClickUp"}
                }},
            ]
            if tags_str:  body.append({"op":"add","path":"/fields/System.Tags",        "value": tags_str})
            if desc_html: body.append({"op":"add","path":"/fields/System.Description", "value": desc_html})
            if not parent_is_promo:
                body.append({"op":"add","path":"/fields/System.AreaPath",     "value": r"Heineken\OMS"})
                body.append({"op":"add","path":"/fields/System.IterationPath","value": r"Heineken\OMS\Kanban"})

            r = requests.post(url, json=body, headers=ADO_HP, timeout=15)
            time.sleep(0.15)
            if r.status_code in (200,201):
                new_id = r.json().get("id")
                att_r  = sync_attachments(new_id, attachments, project, pat_b64)
                results["att_added"] += len(att_r["added"])
                results["created"].append({"title": task["title"][:60], "ado_id": new_id, "project": project, "is_subtask": True})
                print(f"  CREATED subtask: #{new_id} — {task['title'][:50]}")
            else:
                results["errors"].append({"title": task["title"][:60], "reason": f"subtask create HTTP {r.status_code}"})
        else:
            existing = get_ado_item(project, ado_id)
            time.sleep(0.15)
            if not existing: continue
            fields = existing.get("fields",{})
            changes = {}
            if fields.get("Microsoft.VSTS.Common.Priority") != priority:
                changes["Microsoft.VSTS.Common.Priority"] = priority
            if tags_str:
                merged_tags = merge_ado_tags(fields.get("System.Tags","") or "", tags_str)  # additive (v6.5)
                if merged_tags:
                    changes["System.Tags"] = merged_tags
            if not (fields.get("System.Description","") or "").strip():
                desc_text, _ = fetch_full_description(task["item_id"], task["title"])
                dh = markdown_to_ado_html(desc_text)
                if dh: changes["System.Description"] = dh
            if changes:
                update_ado_item(project, ado_id, changes)
                time.sleep(0.15)
                results["updated"].append({"title": task["title"][:60], "ado_id": ado_id, "changed": list(changes.keys()), "is_subtask": True})
                print(f"  UPDATED subtask: #{ado_id} — {task['title'][:50]}")
            else:
                results["unchanged"].append(task["title"][:60])

    except Exception as e:
        results["errors"].append({"title": task["title"][:60], "reason": str(e)})
        print(f"  ERROR subtask: {task['title'][:50]} — {e}")
```

---

## STEP 9 — DELIVER SUMMARY

```
CLICKUP → ADO SYNC — <YYYY-MM-DD HH:MM> (GMT+7)
Mode: INCREMENTAL (since <ISO datetime>) | FULL

User Stories — Created: X | Updated: X | Unchanged: X | Errors: X
Child Tasks  — Created: X | Updated: X | Unchanged: X | Errors: X
Attachments  — Added: X | Skipped (dupe): X | Errors: X
Filtered out: X (wrong status or OMNI-Design)
Total scanned: X (Y parents + Z subtasks)

CREATED: <title> → ADO #<id> | desc: Xc | attachments: +X
UPDATED: <title> → ADO #<id> (changed: <fields>)
ERRORS:  <title> — <reason>

⚠️ COMMENT SIGNAL MISMATCHES DETECTED: X  ← only show if > 0
| Task | Mismatch Type | Detail | Suggestion |
|------|--------------|--------|------------|
| ...  | ...          | ...    | ...        |
```

**NEVER include PAT in any output.**

---

## STEP 10 — SAVE TIMESTAMP (Supabase)

**Always run this step**, even if no changes found.

```python
from datetime import datetime, timezone, timedelta
import time

now_utc  = datetime.now(timezone.utc)
now_gmt7 = now_utc.astimezone(timezone(timedelta(hours=7)))
now_iso  = now_gmt7.strftime("%Y-%m-%d %H:%M GMT+7")

created_us  = [r for r in results["created"]  if not r.get("is_subtask")]
updated_us  = [r for r in results["updated"]  if not r.get("is_subtask")]

# Write ADO sync run to Supabase sync_runs (ADO_SYNC now in constraint)
supabase_sql(f"""
    INSERT INTO sync_runs (sync_type, status, summary)
    VALUES ('ADO_SYNC', 'complete',
        'ADO sync {now_iso} | created:{len(created_us)} updated:{len(updated_us)} unchanged:{len(results["unchanged"])} errors:{len(results["errors"])} | mismatches:{len(ado_mismatches)}')
""")

# Mem0 write removed — Mem0 is retired. sync_runs is the sole timestamp record.

# Log mismatches to Supabase actions if any
if ado_mismatches:
    for m in ado_mismatches:
        action_key = f"ado_mismatch:{m['task_id']}:{m['type']}:{now_utc.strftime('%Y-%m-%d')}"
        supabase_sql(f"""
            INSERT INTO actions (action_key, title, owner, source, priority, status)
            VALUES ('{action_key}',
                    'ADO mismatch [{m["type"]}]: {m["task_name"][:80].replace("'","''")}',
                    'Nghiem', 'ado_sync', 'P2', 'open')
            ON CONFLICT (action_key) DO NOTHING
        """)

print(f"[STEP 10] Timestamp saved: {now_iso} | sync_runs row written (ADO_SYNC)")
```

---

## GUARDRAILS

- ADO 401/403 → abort entire run immediately, log `AUTH_FAILED — rotate PAT`
- Item fail → log error + continue (no silent retry)
- CAP >50 new User Stories in one run → abort + warn
- Duplicate title match → log error, skip
- **NEVER** delete, move, or reassign ADO items (CREATE and UPDATE only)
- **NEVER** include PAT in any log, output, or summary
- `force full sync` or `reset sync` → set `last_run_ts = None`, run FULL MODE, save new timestamp after
- Attachment download fail → log error, skip that file, continue with others
- Attachment dedup: check existing ADO relations by filename (case-insensitive) before every upload
- **NEVER** re-upload an attachment already linked to the ADO work item
- ClickUp `fetch_full_description()` retry: 2 attempts, 0.5s delay between → on both failures write empty desc, never a placeholder
- STEP 3F comment cross-reference is non-blocking — if `cs_by_task` is empty or fails, log and continue
- `acc environment` and `qa environment` statuses are treated as active (included in sync)
- Rate limit: `time.sleep(0.15)` between every ADO API call

---

## CHANGELOG

| Version | Change |
|---|---|
| v6.5 | **Non-destructive tag merge** (2026-06-17). STEP 5: added `merge_ado_tags()`. STEP 7 (parent) + STEP 8 (subtask) EXISTING paths no longer OVERWRITE `System.Tags` with the sync-derived subset — they now ADD only tags not already present (case-insensitive) and keep all existing ADO tags as-is. The old `cur_tags != tags_str → overwrite` rule was destructive: it stripped meaningful ADO tags (`PROMO`, `RejectedClaim`, `v1.0`, `OMS`) and re-cased others (`KH`→`kh`) every run, violating the 'NEVER delete' guardrail. Caught on the 2026-06-17 run where it would have damaged #247104/#249207/#248794. CREATE paths unchanged. No version churn elsewhere. |
| v6.4 | **ACTIVE_STATUSES gap fix + drop-logger** (2026-06-15). STEP 3B: (1) `approved for dev` added to `ACTIVE_STATUSES` — it passed the STEP 3A SQL terminal-status blacklist but was absent from the whitelist, so tasks in that state were silently dropped (e.g. `[ID] Budget Mgmt. and Import`). (2) Added `TERMINAL_STATUSES` set and a drop-logger: any status that is NOT in the whitelist and NOT terminal is now collected and printed as `⚠️ UNLISTED non-terminal statuses dropped`, so future whitelist gaps surface loudly instead of failing silently. `rejected` stays terminal (kept out of ADO). No behavioral change for already-synced statuses. |
| v6.2 | **Status filter fix + title deduplication** (2026-06-04). (1) `ui design`, `in review`, `carpark` moved from SKIP_STATUSES into ACTIVE_STATUSES — all non-closed statuses now sync. SKIP_STATUSES set to empty. (2) STEP 3B2 added: title deduplication — strips known list-suffixes `(REP MGR-1)`, `(PROMO)`, `(PROMO list)` before WIQL check; canonical (unsuffixed) title wins; prevents duplicate ADO items from multi-list ClickUp tasks. |
| v6.1 | **3 bug fixes** (2026-06-03). Fix 1: Status filter contradiction resolved — `open` removed from any skip set, `SKIP_STATUSES` now only contains `in review`, `ui design`, `carpark`. Added `.strip().lower()` normalization so `Open`/`OPEN`/` open ` all match correctly. Fix 2: `ADO_SYNC` added to `sync_runs.sync_type` CHECK constraint (DDL migration applied). STEP 10 now writes to `sync_runs` correctly (no longer falls back to `actions`). Mem0 write removed from STEP 10. Fix 3: STEP 2 timestamp resolution now has explicit priority chain: `sync_runs` → `actions` fallback → FULL MODE. Mem0 legacy read removed entirely. |
| v6.0 | **Supabase-only data source + mandatory fetch_full_description()** (2026-06-01). Tasks loaded from Supabase `source_items` (replaces Mem0 `get_context_pack`). `fetch_full_description()` enforced as MANDATORY for every new item — explicit non-negotiable contract added. Empty-desc backfill added for existing items with blank ADO description. Attachments synced after every CREATE. `sync_runs` table used for ADO timestamp (Mem0 write kept as legacy fallback only). ado_sync.py v2.0 reference script updated with same invariants. |
| v5.2 | **ADO tag source fix** (2026-05-26). ADO tags = `source_tags` (original ClickUp tags) + `module`. Rejects internal operator tags (`MODULE:*`, `OPCO:*` etc.). `resolve_ado_tags()` with live ClickUp fallback added. |
| v5.1 | **STEP 3E MCP-native** (2026-05-25). Replaced Composio `CLICKUP_GET_TASK` with MCP `clickup_get_task(detail_level=detailed)`. Hyperlink stripping accepted, no mitigation. Mismatch notes removed from ADO description. |
| v5.0 | **Phase 3 — Comment signal mismatch detection** (2026-05-24). STEP 3F added: 4 mismatch types. STEP 9 mismatch table. STEP 10 mismatch logging. |
| v4.1 | `fetch_full_description()` hardened: retry, length validation, loud WARN on fallback. |
| v4.0 | STEP 0 refactored to `get_context_pack("ado_sync")`. |
| v3.4 | `markdown_to_ado_html()` `oli` token for numbered lists. |
| v3.3 | Pass 0: external URL image embed stripping. |
| v3.2 | Pass 0: base64 URI strip rewritten greedy DOTALL. |
| v3.1 | STEP 3D: `to do` added to active status filter. |
| v3.0 | STEP 3E live description fetch. STEP 7A attachment sync. |
| v2.0 | `markdown_to_ado_html()` four-pass design. |
| v1.0 | Initial version. |
