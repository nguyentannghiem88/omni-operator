---
name: omni-pulse
version: "1.2"
description: "Lightweight intraday pulse for the OMNI program. Read-only snapshot answering one question: what should Nghiem focus on RIGHT NOW. Max ~150 words output. Reads Supabase only (context pack + open P0/P1 + active risks + today's meetings + reply count). NO writes, NO sync trigger, NO Mem0. Runs anytime, any number of times per day. v1.2: STEP 1B AGENT HEALTH — a one-line heartbeat read over agent_runs (last-tick age / missed-window, consecutive failures, runs today, last-sync age) plus the STEP 1 cache state and the latest learning trend, rendered as a 🟢/🟡/🔴 Agent line; still read-only, business-hours-aware so off-hours gaps are not flagged. v1.1: STEP 2 Q1 recency-gated — pool = recently-active (run_date within 5d) OR due in NOW window (CURRENT_DATE-7 .. +3); sort run_date DESC first. Triggers on: 'pulse', 'run pulse', 'quick status', 'what now', 'what should I focus on', 'status now', 'quick check', 'intraday check', 'agent health', 'heartbeat'."
---

# OMNI Pulse — v1.2

**Purpose:** Instant, ultra-short "what matters right now" snapshot. The fast sibling of
omni-daily-briefing (morning depth) and omni-eod-review (evening depth). Zero writes,
zero side effects — safe to run 10× a day.

```
Pulse = read context → rank by NOW-urgency → print ≤150 words → stop
```

---

## ⚠️ READ FIRST — SHARED CONFIG + UTILS

1. `/mnt/skills/user/omni-config/SKILL.md` → constants (CONFIG_VERSION)
2. `/mnt/skills/user/omni-utils/SKILL.md` → `cache_check()`, `get_context_pack()`, `supabase_sql()`

⛔ Mem0 is retired. Supabase read-only. **This skill never writes to any table** — no
`write_action()`, no context pack writes, no eval records. That is by design: pulse must
stay free of side effects so it can run unlimited times.

---

## STEP 1 — FRESHNESS (1 query, never block)

```python
fresh = cache_check()   # reads sync_runs
```

- `<2h` → proceed silently
- `2–5h` → proceed, append footer: `⏱ Data is <N>h old — run "sync data" if you need live state.`
- `>5h` → proceed anyway, append footer: `⚠️ Data is <N>h old — pulse may be stale. Recommend "sync data".`
- Supabase unavailable → output exactly: `Pulse unavailable — Supabase degraded. Run omni-data-sync or check connection.` and STOP.

⛔ Never auto-trigger a sync. Pulse trades freshness for speed — the footer is the contract.

## STEP 1B — AGENT HEALTH (heartbeat, read-only) ⭐ v1.2

One bounded read over `agent_runs` → a single 🟢/🟡/🔴 line so every pulse doubles as a
heartbeat. Still **zero writes**. Business-hours-aware: outside the 08:00–18:30 GMT+7 weekday
window an idle gap is EXPECTED (no routine ticks), so a long since-last-tick is NOT flagged then.

```python
from datetime import datetime, timezone, timedelta
gmt7 = timezone(timedelta(hours=7)); now = datetime.now(gmt7)
biz = (now.weekday() < 5) and (8 <= now.hour < 19)     # intraday routine window
health = "🟢"; notes = []
try:
    runs = supabase_sql("""
        SELECT run_kind, status, started_at, run_date
        FROM agent_runs ORDER BY started_at DESC LIMIT 40;
    """) or []
    if not runs:
        health, notes = ("🟡", ["no agent_runs yet — routines may not be wired"])
    else:
        def _age_min(ts):
            try: return (now - datetime.fromisoformat(str(ts))).total_seconds()/60
            except Exception: return None
        last_age = _age_min(runs[0]["started_at"])
        consec_fail = 0
        for r in runs:
            if (r.get("status") or "") == "failed": consec_fail += 1
            elif (r.get("status") or "") in ("done","skipped"): break
        today = now.date().isoformat()
        runs_today   = sum(1 for r in runs if str(r.get("run_date"))[:10] == today)
        failed_today = sum(1 for r in runs if str(r.get("run_date"))[:10] == today and r.get("status")=="failed")
        sync_age_h = next((_age_min(r["started_at"])/60 for r in runs
                           if r.get("run_kind") in ("sync","sync_intraday")), None)
        # verdict
        if consec_fail >= 2: health = "🔴"; notes.append(f"{consec_fail} consecutive fails")
        elif consec_fail == 1: health = "🟡"; notes.append("1 recent fail")
        if biz and last_age is not None and last_age > 240:
            health = "🔴"; notes.append(f"no tick in {last_age/60:.0f}h (missed window?)")
        elif biz and last_age is not None and last_age > 120 and health == "🟢":
            health = "🟡"; notes.append(f"last tick {last_age/60:.0f}h ago")
        if sync_age_h is not None and sync_age_h > 6 and health == "🟢":
            health = "🟡"; notes.append(f"sync {sync_age_h:.0f}h old")
    # optional learning-trend / breaker signal (1 tiny read; skip silently if absent)
    try:
        cal = supabase_sql("""
            SELECT content FROM knowledge_facts
            WHERE fact_type='calibration' AND status='active'
            ORDER BY updated_at DESC LIMIT 1;
        """) or []
        tr = (cal[0]["content"].get("trend") if cal else {}) or {}
        if tr.get("ranking_precision") == "degrading" or tr.get("ignored_rate") == "degrading":
            if health == "🟢": health = "🟡"
            notes.append("learning degrading")
    except Exception:
        pass
except Exception as e:
    health, notes = ("🟡", [f"health read skipped: {str(e)[:40]}"])

# build the compact line for STEP 4 (single line, never more):
def _hb():
    if not runs: return f"{health} agent: {'; '.join(notes)}"
    base = f"last tick {last_age/60:.1f}h ago" if (last_age and last_age>=60) else \
           (f"last tick {last_age:.0f}m ago" if last_age is not None else "last tick n/a")
    extra = f" · {runs_today} runs today ({failed_today} fail)" if runs else ""
    tail = f" · {'; '.join(notes)}" if notes else " · clean"
    agent_line = f"{health} agent: {base}{extra}{tail}"
```

> Pure observation. NEVER writes, NEVER auto-fixes, NEVER triggers a sync. If 🔴, the line just
> tells Nghiem to check the routine/connection — remediation is always manual.

## STEP 2 — READ (max 3 queries total)

```sql
-- Q1: NOW-relevant open actions — recency-gated (v1.1)
-- Pool = recently-active OR due inside the NOW window. This keeps fresh null-due
-- items in and drops ancient overdue debris (hard past due_date, no recent signal).
SELECT title, priority, owner, due_date, run_date, is_client_facing, source, source_ref
FROM actions
WHERE status IN ('open','in_progress','blocked')
  AND priority IN ('P0','P1')
  AND ( run_date >= CURRENT_DATE - 5                       -- recently active (incl. null-due)
        OR due_date BETWEEN CURRENT_DATE - 7 AND CURRENT_DATE + 3 )  -- due in NOW window
ORDER BY (priority='P0') DESC,
         run_date DESC NULLS LAST,        -- freshest signal first
         is_client_facing DESC NULLS LAST,
         due_date ASC NULLS LAST
LIMIT 10;
-- NOTE: an item overdue >7d with no run_date activity in last 5d is intentionally
-- dropped here — that is EOD/self-improve hygiene debris, not a NOW focus item.

-- Q2: active risks seen recently
SELECT title, severity, owner FROM risks
WHERE status='open' AND COALESCE(last_seen, run_date) >= CURRENT_DATE - 3
ORDER BY (severity IN ('P1','high')) DESC LIMIT 5;

-- Q3: reply queue count — source-backed ONLY (operator rule)
SELECT count(*) FROM source_items
WHERE source_type='clickup_comment' AND reply_status='pending';
-- Present as "pending comments: N — run reply queue for detail"; never call it "replies needed".
```

Plus today's remaining meetings from the latest `context_packs` payload
(`meetings_to_prepare`) — do NOT call the calendar API.

## STEP 3 — RANK FOR "NOW" (time-aware, GMT+7)

Priority order:
1. P0 client-facing due today / overdue
2. Meetings starting within next 3h that need prep
3. P1 due today, senior stakeholder (Andrea/Zach/Kay Sheng/Kezia/YiLun) items first
4. Active P1 risks with movement in last 72h
5. Everything else → one-line "also open" counter, not listed

Pick **max 5 focus items**. If fewer than 3 qualify, say so — never pad.

## STEP 4 — OUTPUT (hard cap ~150 words)

```markdown
# PULSE — <HH:MM GMT+7>

**Focus now:**
1. <item> — <owner/next step> · <due> (P0)
2. ...
(max 5)

**Next meeting:** <title> at <HH:MM> — <prep yes/no>
**Pending comments:** <N> (run reply queue for detail)
**Open elsewhere:** <N> P1s not shown · <N> active risks
**Agent:** <agent_line from STEP 1B — the 🟢/🟡/🔴 heartbeat, exactly one line>

<freshness footer if applicable>
```

Rules:
- No tables, no sections beyond the template, no executive summary, no decisions register.
- No suggested drafts. If a reply is urgent, point to draft-email-skill instead.
- Plain priorities only; one line per item; source_ref only if asked.

---

## GUARDRAILS

- ⛔ NO Supabase writes of any kind. NO Mem0. NO sync trigger. NO calendar/ClickUp/Outlook API calls — Supabase reads only. The v1.2 health read is SELECT-only over `agent_runs` + `knowledge_facts`; it never writes, never auto-fixes, never triggers a sync.
- ⛔ Never exceed ~150 words. If content competes, cut the lowest-priority focus item — but keep the one-line **Agent:** heartbeat (it is the cheapest, highest-signal line).
- A 🔴 heartbeat only *reports* (missed window / fails / degraded). Remediation (check routine, run sync, reconnect) is always Nghiem's call — pulse never acts on it.
- Never list `needs_review`/`superseded` items — those belong to EOD hygiene.
- Reply counts must be source-backed; label as "pending comments", never "replies needed".
- Pulse never replaces briefing/EOD — if Nghiem asks for depth ("why", "details", "history"), hand off to the appropriate skill.

---

## TRIGGERS

`pulse` | `run pulse` | `quick status` | `what now` | `what should I focus on` |
`status now` | `quick check` | `intraday check` | `agent health` | `heartbeat`

---

## CHANGELOG

| Version | Change |
|---|---|
| v1.2 | **STEP 1B — agent-health heartbeat (P3)** (2026-06-25). Every pulse now ends with one 🟢/🟡/🔴 **Agent:** line so the read-only intraday surface doubles as observability — closing the gap where `agent_runs` was a ledger nothing rolled up. One bounded read (last 40 `agent_runs` rows) → last-tick age / missed-window, consecutive failures, runs-today, last-sync age; plus the STEP 1 cache state and an optional latest-`calibration` trend (breaker-risk) read. Verdict is business-hours-aware (08:00–18:30 GMT+7 weekday) so off-hours idle gaps are NOT flagged as missed ticks. Strictly read-only (SELECT over agent_runs + knowledge_facts) — never writes, never auto-fixes, never triggers a sync; a 🔴 only reports, remediation stays manual. Triggers add `agent health` / `heartbeat`. No change to the focus-ranking logic. |
| v1.0 | Initial. Read-only intraday snapshot: 3-query read, time-aware NOW ranking, ≤150-word output, freshness footer instead of auto-sync, zero side effects. Replaces the missing-on-disk omni-pulse referenced in config §10. |
| v1.1 | STEP 2 Q1 recency-gated. Bug: v1.0 pulled every `due_date <= CURRENT_DATE` so ancient overdue items (Jun 7–12 debris, never closed) dominated, while fresh null-due items fell out of the 2-day window. Fix: pool = `run_date >= CURRENT_DATE-5` OR `due_date BETWEEN CURRENT_DATE-7 AND +3`; sort `run_date DESC` first. Items overdue >7d with no recent signal now drop out (treated as EOD/self-improve hygiene debris, not NOW focus). No schema/behaviour change elsewhere — still read-only. |
