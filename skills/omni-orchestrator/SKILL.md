---
name: omni-orchestrator
version: "1.0"
description: "Agent brain for the OMNI AI Operator — the single entry point that turns the skill toolbox into an autonomous agent. On each tick (external cron via Cowork/Claude Code, or manual 'run operator') it PERCEIVES state (cache_check + agent_runs ledger + current GMT+7 window), DECIDES what is due from omni-config §18 SCHEDULE (idempotency done-today/week, staleness gates, weekday/window, missed-run catch-up), and ACTS by chaining the right skills in order (sync → briefing / sync → EOD → briefing / Monday weekly learning), writing one agent_runs row per step (started→done/failed/skipped) and computing next_due_at. Surface-only tick checks: pending replies, version drift, degraded cache. HARD governance guard — never sends external comms, never commits scope/capacity/SOW. Token-gated: idle when nothing due. Supabase-only (Mem0 retired). Triggers: 'run operator', 'operator', 'heartbeat', 'tick', 'what should the agent do now', 'agent run'."
---

# OMNI Orchestrator — v1.0 (the agent brain)

**Purpose:** Convert the OMNI skill toolbox into a real agent: one entry point that
*perceives → decides → acts → (skills then learn)* on every tick, instead of waiting for a
human to remember which skill to type.

```
tick (cron | "run operator")
  → PERCEIVE   cache_check() + agent_runs ledger + now/window
  → DECIDE     §18 SCHEDULE → due steps (idempotency + staleness + weekday/window + catch-up)
  → ACT        chain skills in order, one agent_runs row per step, compute next_due_at
  → (skills self-improve internally; orchestrator never double-invokes the learning hook)
```

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
   `SCHEDULE_RULES`, `§2 CACHE_*`, `§10 EXPECTED_SKILL_VERSIONS`. CONFIG_VERSION = "1.10".
2. `/mnt/skills/user/omni-utils/SKILL.md` → `cache_check()`, `get_context_pack()`,
   `supabase_sql()`, `write_action()`. UTILITY_VERSION = "11.2".

⛔ Mem0 retired. Supabase only. State table: `agent_runs` (created 2026-06-23). No other new tables.

---

## STEP 0 — BOOTSTRAP

```python
SKILL_VERSION = "1.0"
# 0A. user_time_v0 → now_local (GMT+7), TODAY, weekday
# 0B. trigger = "manual" if user typed a trigger phrase, else "cron" if invoked by scheduler
#     (the external runner passes trigger="cron"; default to "manual")
# 0C. Read §18 SCHEDULE / SCHEDULE_RULES from omni-config (do NOT hardcode here)
# 0D. Version handshake: on-disk vs EXPECTED_SKILL_VERSIONS (§10) — surface drift, never abort
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

---

## TRIGGERS

Auto (cron, trigger="cron"): external scheduler (Cowork / Claude Code) at the §18 windows.
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

---

## CHANGELOG

| Version | Change |
|---|---|
| v1.0 | Initial. Agent-brain entry point: PERCEIVE (cache_check + agent_runs done-today/week) → DECIDE (compile-tested `compute_plan`/`next_due` over §18 SCHEDULE: window/weekday, idempotency, staleness gate, cron-in-window vs manual catch-up) → ACT (ordered skill chaining, one agent_runs row per step started→done/failed/skipped, next_due_at). Surface-only tick checks (replies/drift/degraded). Hard governance + autonomy boundary (read/prepare/learn, never external commit). Token-gated idle. Supabase-only; sole state table `agent_runs`. Does not call self-improve (briefing/EOD already do). Registers in omni-config §10 on approval. |
