---
name: omni-comment-reply-queue
description: "On-demand ClickUp comment reply queue viewer. v3.0: Supabase-only — Mem0 retired. Reads from Supabase source_items WHERE source_type='clickup_comment' AND reply_status='pending'. Live reply verification: calls clickup_get_task_comments for each pending item, checks if latest comment is from someone other than original requester → auto-marks as replied in Supabase (reply_status='replied', linked action status='done'). Filters: module, OPCO, reply_class, human_review. Triggers on: 'show reply queue', 'check reply queue', 'what comments need my reply', 'pending comment replies', 'any comments waiting for me'."
---

# OMNI Comment Reply Queue — v3.0

On-demand viewer for ClickUp comments requiring Nghiem's response.
Primary source: Supabase `source_items WHERE source_type='clickup_comment' AND reply_status='pending'`
**v3.0 feature**: Live reply verification — checks ClickUp for latest comment; auto-resolves if already replied.

---

## ⚠️ READ FIRST — SHARED CONFIG + UTILS

**Before any step, read:**
1. `/mnt/skills/user/omni-config/SKILL.md` → loads constants
2. `/mnt/skills/user/omni-utils/SKILL.md` → loads utilities

---

## STEP 0 — PARSE FILTERS FROM USER INPUT

```python
filters = {
    "module":       None,   # REP|LOOP|HAP|PEM|OMS|CC|OMNI
    "opco":         None,   # MY|ID|KH|LA|TW|IN|MM
    "human_review": None,   # True/False
    "urgency":      None,   # today|this_week|sprint|none
    "task_id":      None,   # specific ClickUp task ID
}
```

---

## STEP 1 — LOAD PENDING ITEMS FROM SUPABASE

```python
rows = supabase_sql("""
    SELECT
        id, external_id, item_id, title, summary, sender,
        module, market, status, priority, tags, source_url,
        reply_status, raw_json, item_created_at, synced_at
    FROM source_items
    WHERE source_type = 'clickup_comment'
      AND reply_status = 'pending'
    ORDER BY item_created_at DESC
""")

if not rows:
    print("📬 COMMENT REPLY QUEUE — No pending items found.")
    print("All comments resolved, or run omni-data-sync to refresh.")
    # Stop here
```

Apply filters from STEP 0:
```python
pending = rows or []

if filters["module"]:
    pending = [r for r in pending if (r.get("module") or "").upper() == filters["module"].upper()]
if filters["opco"]:
    pending = [r for r in pending if (r.get("market") or "").upper() == filters["opco"].upper()]
if filters["task_id"]:
    pending = [r for r in pending if filters["task_id"] in (r.get("raw_json", {}).get("task_id") or "")]

print(f"Pending reply items loaded: {len(pending)}")
```

---

## STEP 1B — LIVE REPLY VERIFICATION ⭐ v3.0

For each pending item, call `clickup_get_task_comments` to check if it has already been replied to.

**Logic:**
- Get `requester_username` and `comment_date_ms` from `raw_json`
- Fetch live comments for the task
- Find the **latest comment** with `date > comment_date_ms`
- If latest comment author ≠ `requester_username` → **already replied** → auto-resolve

```python
# Pre-load ClickUp tool
tool_search("ClickUp get task comments")

auto_resolved = []   # items verified as replied
still_pending = []   # items confirmed still needing reply

for item in pending:
    rj = item.get("raw_json") or {}
    task_id          = rj.get("task_id")
    requester        = rj.get("requester_username", "")
    signal_date_ms   = int(rj.get("comment_date_ms", 0))

    if not task_id or not signal_date_ms:
        # Missing reference data — cannot verify, keep as pending
        still_pending.append(item)
        continue

    try:
        result = clickup_get_task_comments(task_id=task_id)
        comments = result.get("comments", []) if result else []
    except Exception as e:
        print(f"  [WARN] Comment fetch failed for task {task_id}: {e} — keeping pending")
        still_pending.append(item)
        continue

    # Find latest comment AFTER the signal comment
    later_comments = [
        c for c in comments
        if int(c.get("date", 0)) > signal_date_ms
    ]

    if not later_comments:
        # No new comments since signal — still pending
        still_pending.append(item)
        continue

    # Sort by date descending — get the most recent
    later_comments.sort(key=lambda c: -int(c.get("date", 0)))
    latest = later_comments[0]
    latest_author   = latest.get("user", {}).get("username") or latest.get("user", {}).get("email") or ""
    latest_date_ms  = int(latest.get("date", 0))

    # Replied if: latest comment is from someone other than the original requester
    # (Nghiem replied, or another team member replied)
    if latest_author.lower() != requester.lower():
        auto_resolved.append({
            "item":          item,
            "replied_by":    latest_author,
            "replied_at_ms": latest_date_ms,
        })
    else:
        # Requester posted again (follow-up / still waiting)
        still_pending.append(item)

print(f"Live verification: {len(auto_resolved)} auto-resolved, {len(still_pending)} still pending")
```

### Auto-resolve: write back to Supabase

```python
from datetime import datetime, timezone, timedelta
gmt7 = timezone(timedelta(hours=7))

for r in auto_resolved:
    item       = r["item"]
    replied_by = r["replied_by"]
    replied_at = datetime.fromtimestamp(r["replied_at_ms"] / 1000, tz=gmt7).strftime("%Y-%m-%d %H:%M GMT+7")
    item_ext_id = item.get("external_id") or item.get("item_id")
    rj = item.get("raw_json") or {}
    task_id = rj.get("task_id")

    # 1. Mark source_items row as replied
    supabase_sql(f"""
        UPDATE source_items
        SET reply_status = 'replied',
            raw_json = raw_json || jsonb_build_object(
                'replied_by', '{replied_by}',
                'replied_at', '{replied_at}'
            ),
            updated_at = NOW()
        WHERE source_type = 'clickup_comment'
          AND external_id = '{item_ext_id}'
    """)

    # 2. Mark linked action as done
    if task_id:
        supabase_sql(f"""
            UPDATE actions
            SET status = 'done', updated_at = NOW()
            WHERE source = 'clickup_comment'
              AND source_ref LIKE '%{task_id}%'
              AND status = 'open'
        """)

    print(f"  [AUTO-RESOLVED] '{item.get('title','')[:50]}' — replied by {replied_by} at {replied_at}")
```

---

## STEP 2 — RENDER OUTPUT

### Header

```
📬 COMMENT REPLY QUEUE — {now GMT+7}
{len(still_pending)} pending | {len(auto_resolved)} auto-resolved this check
{if filters applied: Filters: <applied> → showing X of Y}
```

### Auto-resolved section (show if any)

```
✅ AUTO-RESOLVED ({len(auto_resolved)})
These comments were already replied to — marked as done:

  · [Task name] — replied by {replied_by} ({relative time, e.g. "30 mins ago"})
  · ...
```

### If still_pending is empty:

```
✅ No pending replies remaining.
```
→ Stop.

### Pending items table

Sort order: client-facing first → highest priority → oldest signal first (most urgent to reply).

```python
still_pending.sort(key=lambda r: (
    0 if r.get("is_client_facing") else 1,
    0 if (r.get("priority") or "") == "P1" else 1,
    r.get("item_created_at") or ""   # oldest first
))
```

```
| # | Task | OPCO/Module | From | Signal | Summary | Suggested Action |
|---|------|-------------|------|--------|---------|-----------------|
```

**Column rules:**
- `#` → row number
- `Task` → title (≤45 chars) linked via `source_url` if available: `[name](url)`
- `OPCO/Module` → `{market}/{module}` or `—`
- `From` → `sender` (comment author)
- `Signal` → signal type from tags (first non-OPCO/MODULE tag), with emoji:
  - FOLLOW_UP → `❓`
  - ACTION → `⚡`
  - BLOCKER → `🔴`
  - CLIENT_CONCERN → `🟠`
  - RISK_ESCALATION → `⚠️`
  - default → `💬`
- `Summary` → `summary` field (≤20 words)
- `Suggested Action` → from linked action `title` in actions table, or derive from summary

### Footer

```
─────────────────────────────────────────────
💡 Reply in ClickUp directly — never auto-posted.
   Auto-resolve runs on next queue check after you reply.

To filter: "show HAP replies" | "only Malaysia" | "urgent only"
To refresh: "run data sync"
```

---

## STEP 3 — OPTIONAL: DETAIL VIEW

If user asks for details on a specific task:

```
📋 DETAIL — {task_name}

Task URL: {source_url}
Module/OPCO: {module} / {market}
From: {sender} at {item_created_at}
Signal: {signal_type}
Summary: {summary}

reply_status: pending
requester: {raw_json.requester_username}
signal_date: {raw_json.comment_date_ms → ISO}

Live check: {latest comment found / not found}
```

---

## GUARDRAILS

- **Never auto-post** replies — only verify and display
- **Live fetch is per-pending-item only** — never fetch comments for already-resolved items
- **Auto-resolve is idempotent** — re-running the queue check never double-writes
- If `clickup_get_task_comments` fails for a task → keep as pending, log warn, do NOT resolve
- If `raw_json.requester_username` is missing → keep as pending (cannot verify safely)
- If `raw_json.comment_date_ms` is 0 or missing → keep as pending
- **Same-author follow-up rule**: if requester posted again after the signal → still pending (they're chasing)
- Supabase write failures on auto-resolve → log error, show item as resolved in UI but note "⚠️ DB write failed — may reappear"

---

## TRIGGERS

- "show reply queue"
- "check reply queue"
- "what comments need my reply"
- "pending comment replies"
- "comment reply queue"
- "what do I need to reply to in ClickUp"
- "any comments waiting for me"
- "show me unanswered comments"
- "ClickUp replies pending"

Optional filter modifiers: module name, OPCO code, "urgent only", task ID.

---

## CHANGELOG

| Version | Change |
|---|---|
| v3.0 | **Live reply verification** (2026-05-29). STEP 1B added: fetches live ClickUp comments per pending item, auto-resolves if latest comment is from non-requester. Auto-resolve writes `reply_status='replied'` to source_items and flips linked action to `done`. Requires `reply_status` column (DDL: `ALTER TABLE source_items ADD COLUMN reply_status text DEFAULT 'pending'`). Requires `raw_json.requester_username` + `raw_json.comment_date_ms` written by `omni-data-sync` v12.1 STEP 4F-5. |
| v2.0 | Supabase-only — Mem0 retired. Reads from Supabase source_items WHERE source_type='clickup_comment' AND 'reply_needed'=ANY(tags). |
| v1.0 | Initial version. Reads `[CLICKUP-COMMENT-REPLY-QUEUE]` from Mem0. |
