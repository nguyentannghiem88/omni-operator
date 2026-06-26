---
name: omni-orchestrator
version: "1.1"
description: "Agent brain for the OMNI AI Operator — single entry point turning the skill toolbox into an autonomous agent. v1.1: trigger='event' reads omni-config §18 EVENT_TICKS and runs ONE matching fast-path (p0_incident, client_email, governance_comment, ado_build_break) then stops — dedupe on (type,ref), one agent_runs row, draft/surface ONLY, governance events route VN-GOV, never send/commit. On a clock tick (cron/manual) it PERCEIVES (cache_check + agent_runs + GMT+7 window), DECIDES what's due from §18 SCHEDULE (idempotency, staleness gates, weekday/window, catch-up, plus the v1.14 hourly intraday pulse), and ACTS by chaining skills in order, one agent_runs row per step. Surface-only tick checks: replies, drift, degraded cache. HARD governance guard — never sends external comms, never commits scope/capacity/SOW. Token-gated idle. Supabase-only. Triggers: 'run operator', 'operator', 'heartbeat', 'tick', 'agent run', 'what should the agent do now'; plus runner-fired event ticks."
---

# OMNI Orchestrator — v1.1 (the agent brain)

**Purpose:** Convert the OMNI skill toolbox into a real agent: one entry point that
*perceives → decides → acts → (skills then learn)* on every tick, instead of waiting for a
human to remember which skill to type.

```
tick (cron | "run operator" | EVENT)
  ├─ trigger ∈ {cron, manual}  → PERCEIVE → DECIDE (§18 SCHEDULE) → ACT (chain due steps)
  └─ trigger == "event"        → STEP 2E: match §18 EVENT_TICKS → run ONE fast-path → STOP
  → (skills self-improve internally; orchestrator never double-invokes the learning hook)
```

A **clock tick** sweeps the time schedule (morning sync+briefing / evening sync+EOD+briefing /
Monday learning / hourly intraday pulse). An **event tick** is reactive: it skips the schedule
entirely, runs the one declared fast-path for that event type, and stops. Both inherit the same
hard governance guard — read / prepare / DRAFT / surface only, never external commitment.

The orchestrator does NOT replace any skill. It schedules and chains them. The fast learning
loop still fires inside briefing/EOD (their STEP 8/6 self-improve hook); the weekly loop is just
another scheduled step here.

---

## ⛔ AUTONOMY BOUNDARY (read first — non-negotiable)

| The orchestrator MAY (autonomous) | The orchestrator MUST NEVER |
|---|---|
| Run sync / briefing / EOD / pulse / weekly-learning on schedule | Send any external email/Teams message |
| Read, prepare, surface, log to `agent_runs` | Commit scope / capacity / SOW / cost |
| Surface pending replies, drift, degraded cache | Auto-confirm a `GOVERNANCE_REVIEW` item |
| Skip / catch up missed runs idempotently | Externally confirm anything routed through VN-GOV |

Autonomy here is **read / prepare / learn**, never **external commitment**. VN-GOV
(Delivery → Ha Hoang → YiLun → Andrea, Peter CC) is constitution-level and untouched. A
`run operator` tick may *draft* and *surface*, but a human still sends and commits.

---

## ⚠️ READ FIRST — SHARED CONFIG + UTILS

1. `/mnt/skills/user/omni-config/SKILL.md` → `§18 SCHEDULE`, `SCHEDULE_TICK_CHECKS`,
   `SCHEDULE_RULES`, **`EVENT_TICKS` + `EVENT_TICK_RULES` (v1.14 — read for trigger='event')**,
   `§2 CACHE_*`, `§10 EXPECTED_SKILL_VERSIONS`. CONFIG_VERSION = "1.15".
2. `/mnt/skills/user/omni-utils/SKILL.md` → `cache_check()`, `get_context_pack()`,
   `supabase_sql()`, `write_action()`. UTILITY_VERSION = "11.2".

⛔ Mem0 retired. Supabase only. State table: `agent_runs` (created 2026-06-23). No other new tables.

---

## STEP 0 — BOOTSTRAP

```python
SKILL_VERSION = "1.1"
# 0A. user_time_v0 → now_local (GMT+7), TODAY, weekday
# 0B. trigger = "manual" if user typed a trigger phrase;
#     "event"  if the external runner passed an `event` payload (see 0E);
#     else "cron" if invoked by the scheduler. (Default to "manual".)
# 0C. Read §18 SCHEDULE / SCHEDULE_RULES / EVENT_TICKS / EVENT_TICK_RULES from omni-config
#     (do NOT hardcode here)
# 0D. Version handshake: on-disk vs EXPECTED_SKILL_VERSIONS (§10) — surface drift, never abort
# 0E. EVENT PAYLOAD (only when trigger=="event"): the runner passes
#       event = {"type":   <p0_incident|client_email|governance_comment|ado_build_break>,
#                "ref":    <stable id: source_item id / email id / comment id / ado work-item id>,
#                "source": <"teams"|"outlook"|"clickup"|"ado">}
#     Validate event["type"] ∈ EVENT_TICKS keys. Unknown/missing type → STEP 2E logs + idles
#     (NEVER guess a fast-path for an unrecognized event).
```

---

## STEP 1 — PERCEIVE

```python
# 1A. Freshness + degraded
cc = cache_check()                      # → {age_h, degraded, source}
cache_age_h = cc.get("age_h")
degraded    = cc.get("degraded", False)

# 1B. What has already run today / this week (idempotency source of truth = agent_runs)
done_today = supabase_sql("""
  SELECT DISTINCT run_kind FROM agent_runs
  WHERE run_date = CURRENT_DATE AND status = 'done';""") or []
done_week  = supabase_sql("""
  SELECT DISTINCT run_kind FROM agent_runs
  WHERE date_trunc('week', run_date) = date_trunc('week', CURRENT_DATE)
    AND status = 'done';""") or []
done_today = {r["run_kind"] for r in done_today}
done_week  = {r["run_kind"] for r in done_week}
```

---

## STEP 2 — DECIDE (the decision core — compile-tested, do not paraphrase)

> **Routing:** if `trigger == "event"` → **SKIP STEP 2 and STEP 3 entirely** and go to **STEP 2E**.
> The schedule decision core below runs ONLY for `trigger ∈ {cron, manual}`. An event tick never
> consults the time windows.

```python
from datetime import datetime, date, time, timedelta
WEEKDAYS = {"MO":0,"TU":1,"WE":2,"TH":3,"FR":4,"SA":5,"SU":6}
def _hhmm(s): h,m = s.split(":"); return time(int(h), int(m))

def compute_plan(schedule, now_local, trigger, done_today, done_week, cache_age_h):
    """Ordered list of (job, step, action) — action ∈ {run, skip_done, skip_fresh}.
       cron acts only inside the window; manual allows same-day / same-week catch-up."""
    plan = []
    for job in schedule:
        wd = job.get("weekday")
        start_dt = datetime.combine(now_local.date(), _hhmm(job["window"][0]), tzinfo=now_local.tzinfo)
        end_dt   = datetime.combine(now_local.date(), _hhmm(job["window"][1]), tzinfo=now_local.tzinfo)
        if wd is None:
            opened    = now_local >= start_dt
            in_window = start_dt <= now_local <= end_dt
        else:
            target    = WEEKDAYS[wd]
            opened    = (now_local.weekday() > target) or (now_local.weekday()==target and now_local>=start_dt)
            in_window = (now_local.weekday()==target and start_dt <= now_local <= end_dt)
        eligible = in_window if trigger == "cron" else opened
        if not eligible:
            continue
        for step in job["steps"]:
            rk = step["run_kind"]
            if step.get("once_per_week") and rk in done_week:
                plan.append((job["job"], step, "skip_done")); continue
            if step.get("once_per_day") and rk in done_today:
                plan.append((job["job"], step, "skip_done")); continue
            gate = step.get("staleness_gate_h")
            if gate is not None and cache_age_h is not None and cache_age_h <= gate:
                plan.append((job["job"], step, "skip_fresh")); continue
            plan.append((job["job"], step, "run"))
    return plan

def next_due(schedule, now_local):
    """Earliest upcoming window-start across all jobs (searches next 8 days)."""
    cands = []
    for job in schedule:
        wd = job.get("weekday")
        for d in range(0, 8):
            day = now_local.date() + timedelta(days=d)
            if wd is not None and day.weekday() != WEEKDAYS[wd]:
                continue
            cand = datetime.combine(day, _hhmm(job["window"][0]), tzinfo=now_local.tzinfo)
            if cand > now_local:
                cands.append((cand, job["job"])); break
    return min(cands) if cands else (None, None)

plan = compute_plan(SCHEDULE, now_local, trigger, done_today, done_week, cache_age_h)
```

If `plan` has no `run`/`skip_*` entries → **idle**: print the idle line (STEP 5) and STOP.
Idle is free — no ledger row, no skill calls.

---

## STEP 3 — ACT (chain skills, one ledger row per step)

For each `(job, step, action)` in `plan`, in order:

```python
if action == "skip_done":
    _ledger(step, status="skipped", reason="already_done")      # cheap row, keeps audit complete
    continue
if action == "skip_fresh":
    _ledger(step, status="skipped", reason="cache_fresh")
    continue

# action == "run":
run_id = _ledger_start(step, trigger)        # INSERT status='started' RETURNING id
try:
    # MANDATORY: read the target skill before executing it
    read("/mnt/skills/user/<step['skill']>/SKILL.md")
    result = execute(step["skill"], mode=step.get("mode"))   # the real chained run
    _ledger_finish(run_id, status="done", summary=result.summary,
                   next_due_at=next_due(SCHEDULE, now_local)[0])
except Exception as e:
    _ledger_finish(run_id, status="failed", summary=str(e)[:300])
    # fail-open: continue to later steps UNLESS this is a sync whose failure leaves the
    # context degraded — then mark the dependent briefing/EOD degraded and surface it.
    if step["run_kind"] == "sync" and degraded:
        mark_remaining_dependent_degraded(plan)
```

Ledger helpers (Supabase `agent_runs`):

```python
def _ledger_start(step, trigger):
    return supabase_sql(f"""
      INSERT INTO agent_runs (run_date, run_kind, mode, status, trigger, started_at)
      VALUES (CURRENT_DATE, '{step['run_kind']}', {sql_lit(step.get('mode'))},
              'started', '{trigger if trigger in ('cron','manual') else 'chained'}', now())
      RETURNING id;""")[0]["id"]

def _ledger_finish(run_id, status, summary, next_due_at=None):
    supabase_sql(f"""
      UPDATE agent_runs SET status='{status}', finished_at=now(),
        summary={sql_lit(summary)}, next_due_at={sql_lit(next_due_at)},
        raw_json = raw_json || jsonb_build_object('finished','{now_str}')
      WHERE id='{run_id}';""")

def _ledger(step, status, reason):   # for skip rows — single insert, already terminal
    supabase_sql(f"""
      INSERT INTO agent_runs (run_date, run_kind, mode, status, trigger, finished_at, summary, raw_json)
      VALUES (CURRENT_DATE, '{step['run_kind']}', {sql_lit(step.get('mode'))},
              '{status}', '{trigger}', now(), {sql_lit(reason)},
              jsonb_build_object('reason','{reason}'));""")
```

`sql_lit()` is the standard NULL-safe quoter from omni-utils. Steps chained by the
orchestrator log `trigger='chained'` on their own internal action logs; the agent_runs row
keeps the originating trigger (`cron`/`manual`).

**Note:** briefing/EOD already run `omni-self-improve` as their final internal step, so the
behavioral learning loop fires automatically — the orchestrator does NOT call self-improve.

---

## STEP 2E — EVENT FAST-PATH (trigger == "event" only — short-circuits the schedule)

Reaches here ONLY when `trigger == "event"`. Reads §18 `EVENT_TICKS` + `EVENT_TICK_RULES`.
Runs the ONE declared fast-path for the event type, writes ONE `agent_runs` row, then STOPS.
No schedule sweep, no `compute_plan`, no `next_due` gating of steps.

```python
ev   = event                                  # {"type","ref","source"} from STEP 0E
spec = EVENT_TICKS.get(ev["type"])

# Unknown type → never guess a fast-path. Log idle and stop.
if spec is None:
    supabase_sql(f"""INSERT INTO agent_runs
      (run_date, run_kind, status, trigger, finished_at, summary, raw_json)
      VALUES (CURRENT_DATE, 'event:{ev['type']}', 'skipped', 'event', now(),
              'unknown_event_type', jsonb_build_object('ref', {sql_lit(ev['ref'])}));""")
    print(f"🤖 Operator event — unknown type '{ev['type']}' — ignored."); STOP

# Idempotency (EVENT_TICK_RULES['idempotency']): dedupe on (type, ref) within today so a
# webhook retry can never double-draft / double-surface.
seen = supabase_sql(f"""
  SELECT 1 FROM agent_runs
  WHERE run_date = CURRENT_DATE AND run_kind = 'event:{ev['type']}'
    AND raw_json->>'ref' = {sql_lit(ev['ref'])} AND status IN ('started','done')
  LIMIT 1;""")
if seen:
    print(f"🤖 Operator event — {ev['type']}:{ev['ref']} already handled today — skip."); STOP

# One ledger row for the whole event (NOT one per fast-path step — per EVENT_TICK_RULES['ledger']).
run_id = supabase_sql(f"""
  INSERT INTO agent_runs (run_date, run_kind, mode, status, trigger, started_at, raw_json)
  VALUES (CURRENT_DATE, 'event:{ev['type']}', NULL, 'started', 'event', now(),
          jsonb_build_object('ref', {sql_lit(ev['ref'])}, 'source', {sql_lit(ev.get('source'))}))
  RETURNING id;""")[0]["id"]

# fast_path entries are descriptors, e.g. "omni-data-sync(LIGHTWEIGHT, ungated)",
# "omni-pulse", "draft-email-skill(reply DRAFT)", "ado-oms-knowledge-sync(incremental)".
def _parse(desc):
    name = desc.split("(")[0].strip()
    hint = desc[desc.find("(")+1:desc.rfind(")")].lower() if "(" in desc else ""
    mode = "LIGHTWEIGHT" if "lightweight" in hint else ("FULL" if "full" in hint else None)
    return name, mode, hint            # hint carries ungated / draft / single thread / incremental / comments on

results = []
for desc in spec["fast_path"]:
    skill, mode, hint = _parse(desc)
    read(f"/mnt/skills/user/{skill}/SKILL.md")          # MANDATORY before executing any skill
    try:
        # 'ungated' = fetch fresh NOW (an event ignores the staleness gate). draft-email runs in
        # DRAFT mode only — its output is surfaced, never sent (enforced by GUARDRAILS below).
        r = execute(skill, mode=mode, event_ref=ev["ref"], hints=hint)
        results.append({"skill": skill, "status": "done", "summary": getattr(r, "summary", "")})
    except Exception as e:
        results.append({"skill": skill, "status": "failed", "summary": str(e)[:200]})
        # fail-open: a failed prep step still lets later steps + the surface proceed.

_ledger_event_finish(run_id, status="done",
    summary=f"event:{ev['type']} ref={ev['ref']} → " +
            ", ".join(f"{r['skill']}:{r['status']}" for r in results))
# STOP here — an event tick never runs STEP 3 (schedule ACT). STEP 4 tick-checks still apply.
```

**Per-event SURFACE + AUTONOMY** (apply `spec["surface"]` and `spec["autonomy"]`):

| Event | Surface (internal) | ⛔ Autonomy ceiling |
|---|---|---|
| `p0_incident` | Headline incident + owner + nearest prior `risks` flag (note lead-time → feeds recall). Raise an **internal** P0 action. | Draft/surface only. NEVER message the client or commit a fix ETA. |
| `client_email` | Extracted ask + a ready reply **DRAFT** in Nghiem's style (`Hi @Name` / `Regards, Nghiem`). Queue a reply-required action. | DRAFT ONLY — surfaced for human send. **If the ask is capacity/SOW/scope-class → do NOT draft a client reply; reclassify to the governance route.** |
| `governance_comment` | Flag `GOVERNANCE_REVIEW`; route **VN-GOV** (Delivery → Ha Hoang → YiLun → Andrea, Peter CC); surface an **internal** summary. | ⛔ HARD STOP on external action. Constitution-level. Never a client-facing draft, never auto-send, never a direct reply to Andrea. |
| `ado_build_break` | Name the failing item + likely owner from recent ADO activity. Raise an **internal** P1 action. | Surface only. Never push code, never edit the pipeline. |

```python
# Governance reclassification guard (covers a client_email whose content is actually governance):
governance_class = (ev["type"] == "governance_comment") or _looks_governance(results)
if governance_class:
    route_vn_gov_surface_only()        # NEVER draft/queue a direct external reply to Andrea/YiLun
```

`_ledger_event_finish` mirrors STEP 3's finisher (UPDATE status/finished_at/summary on the row;
no `next_due_at` needed — events are not scheduled).

---

## STEP 4 — TICK CHECKS (surface-only, every tick, no side effects)

Per `SCHEDULE_TICK_CHECKS`. Read from the context pack already loaded; do not re-fetch.

```python
pack = get_context_pack("briefing")          # cached read
replies = len(pack.get("clickup_replies_needed", []))
drift   = [s for s in on_disk_versions if on_disk_versions[s] != EXPECTED_SKILL_VERSIONS.get(s)]
# Surface only — NEVER auto-reply, NEVER auto-fix drift, NEVER silent-proceed on degraded.
```

---

## STEP 5 — OUTPUT (compact)

Idle:
```
🤖 Operator tick (<now GMT+7>, <trigger>) — nothing due.
   Next: <job> at <next_due_at GMT+7>.
   <only if non-zero>  📬 <n> replies waiting · ⚠️ drift: <skills> · 🔴 cache degraded
```

Active:
```
🤖 Operator tick — <now GMT+7> (<trigger>)
   ▶ ran:     <run_kind>(<status>) ... in order
   ⏭ skipped: <run_kind>(<reason>) ...
   📬 replies: <n>   ⚠️ drift: <skills|none>   cache: <fresh|degraded>
   ⏭ next due: <job> at <next_due_at GMT+7>
```
Then the chained skills' own outputs render beneath (briefing/EOD print as normal). The
orchestrator header stays ≤6 lines — it must not restate the briefing/EOD content.

Event (`trigger == "event"`):
```
🤖 Operator event — <type>:<ref> (<source>, <now GMT+7>)
   ▶ fast-path: <skill>(<status>) → <skill>(<status>) ...
   📌 surface:  <one-line internal summary per the event's SURFACE row>
   ⛔ autonomy: draft/surface only <· VN-GOV routed, if governance-class>
```
The drafted reply / pulse / incident summary renders beneath. NEVER an outbound send.

---

## STEP 6 — LOG

The per-step `agent_runs` rows ARE the run log — no separate `write_action()` needed for the
orchestrator itself (avoids polluting `actions`). Chained skills keep their own action logs.

---

## GUARDRAILS

- ⛔ NEVER send external comms or commit scope/capacity/SOW — read/prepare/learn only.
- ⛔ NEVER auto-confirm a GOVERNANCE_REVIEW item or anything routed through VN-GOV.
- ⛔ NEVER edit `/mnt/skills/user/` files. Drift is surfaced, never auto-fixed.
- Idempotency is mandatory: a once_per_day/week step already `done` today/this week is skipped.
- Staleness gate is mandatory: never re-fetch when cache is within the gate.
- Fail-open: one failed step never blocks the rest (except sync-failure-while-degraded → surface).
- Token-gated: idle costs nothing — no ledger row, no skill calls when `plan` is empty.
- Read the target SKILL.md before executing any chained skill.
- No new tables/columns beyond `agent_runs`.
- **Event ticks (v1.1):** single-shot — run ONE matching `EVENT_TICKS` fast-path then STOP; never
  sweep the schedule. Dedupe on (type, ref) per day — a webhook retry must not double-act. A
  `client_email` fast-path may DRAFT a reply but NEVER send it; a `governance_comment` (or any
  governance-class `client_email`) is HARD-STOPPED from any external draft and routed VN-GOV
  (Ha Hoang → YiLun → Andrea, Peter CC) as an internal surface only. Unknown event type → log + idle.

---

## TRIGGERS

Auto (cron, trigger="cron"): external scheduler (Cowork / Claude Code) at the §18 windows
(morning, evening, Monday learning, and the v1.14 hourly intraday pulse).
Event (trigger="event"): external webhook/poller fires `run operator` with an `event` payload
{type, ref, source}; the orchestrator runs the matching §18 `EVENT_TICKS` fast-path. No webhook
yet → the intraday job already catches the same signals within ≤1 tick; events just make it immediate.
On demand (trigger="manual"): `run operator` | `operator` | `heartbeat` | `tick` |
`agent run` | `what should the agent do now`

---

## VALIDATION (before wiring any cron)

1. **Decision core** unit-tests pass (run standalone): morning-in-window runs sync+briefing;
   re-tick same day skips both `skip_done`; before 08:30 → idle with correct next_due;
   Monday weekly_learning due, Tue catch-up still due if not done this week; manual catch-up
   after window runs, cron after window does not.
2. **Dry-run** `run operator` against live state with execution stubbed (log to agent_runs,
   do not actually chain) — confirm the plan matches what a human expects for the current time.
3. Only after 1–2 pass: enable real chaining, then (separately) wire the external cron.
4. **Event branch (v1.1):** dry-run each `EVENT_TICKS` type with execution stubbed — confirm
   (a) a known type runs exactly its declared fast-path and STOPS (no schedule sweep);
   (b) a duplicate (type, ref) the same day logs `event_seen` and does nothing;
   (c) an unknown type logs `unknown_event_type` + idles;
   (d) `governance_comment` and a governance-class `client_email` both route VN-GOV with NO
   external draft; a normal `client_email` produces a DRAFT only (never a send).
   Only after these pass: let the external runner fire real `trigger="event"` ticks.

---

## CHANGELOG

| Version | Change |
|---|---|
| v1.1 | **Event-driven reaction (2026-06-25).** Added `trigger="event"` handling so the agent reacts to signals, not just the clock. STEP 0 gains 0E event-payload parse ({type,ref,source}, validated against §18 `EVENT_TICKS`). STEP 2 gains a routing guard — an event tick SKIPS the schedule decision core and STEP 3 entirely. New **STEP 2E** runs the one declared fast-path for the event type, with: dedupe on (type,ref) per day (webhook-retry safe), ONE `agent_runs` row `run_kind='event:<type>'` `trigger='event'`, mandatory SKILL.md read before each fast-path skill, fail-open per step, and a per-event SURFACE+AUTONOMY table (p0_incident / client_email / governance_comment / ado_build_break). Hard autonomy ceiling preserved and tightened: `client_email` DRAFTS only (never sends); `governance_comment` and any governance-class `client_email` are HARD-STOPPED from external drafting and routed VN-GOV (Ha Hoang → YiLun → Andrea, Peter CC) as internal surface only; unknown type → log+idle. STEP 5 gains an event output block; GUARDRAILS/TRIGGERS/VALIDATION extended. Reads omni-config §18 `EVENT_TICKS`+`EVENT_TICK_RULES` (config handshake → 1.15). No new tables/columns — reuses `agent_runs`. Registers in §10 (orchestrator 1.0→1.1) via the companion config 1.15 registry bump. |
| v1.0 | Initial. Agent-brain entry point: PERCEIVE (cache_check + agent_runs done-today/week) → DECIDE (compile-tested `compute_plan`/`next_due` over §18 SCHEDULE: window/weekday, idempotency, staleness gate, cron-in-window vs manual catch-up) → ACT (ordered skill chaining, one agent_runs row per step started→done/failed/skipped, next_due_at). Surface-only tick checks (replies/drift/degraded). Hard governance + autonomy boundary (read/prepare/learn, never external commit). Token-gated idle. Supabase-only; sole state table `agent_runs`. Does not call self-improve (briefing/EOD already do). Registers in omni-config §10 on approval. |
