---
name: omni-utils
description: "Shared utility library for all OMNI skills. v11.0: Supabase-ONLY mode — Mem0 fully retired; all Mem0 functions return SKIPPED. write_action() writes to Supabase actions table. supabase_sql() raises on error. New helpers: upsert_knowledge_fact(), upsert_user_preference(), upsert_project_context(). client_facing_open_actions replaces waiting_on_client. v11.1: Feature Status Rollup — new feature_status table (DDL), load_feature_registry_seed(), resolve_feature_key(), rollup_feature_status(), get_feature_rollup(); context pack gains feature_rollup field; auto-supersede per omni-config FEATURE_AUTOSUPERSEDE. v11.2: build_context_pack_from_supabase() decisions query filters superseded_by IS NULL so omni-data-sync v12.5 STEP 7A-DEDUP merges actually render; reconciles description/changelog to the 11.2 constant. UTILITY_VERSION = '11.2'. READ-ONLY — never execute directly."
---

# OMNI Shared Utilities — v11.1 (Supabase-Only + Feature Rollup)

**Purpose:** Single source of truth for all shared logic across OMNI skills.  
**Read by:** `omni-data-sync`, `omni-daily-briefing`, `omni-eod-review`, `omni-clickup-ado-sync`, `draft-email-skill`, `omni-sent-analyzer`, `requirement-analyzer-compact`, and all new skills.  
**Rule:** Never copy-paste these functions into other skills. Always reference this file.

---

## ⚠️ READ FIRST — SHARED CONFIG

**Before using any utility, read `/mnt/skills/user/omni-config/SKILL.md`.**

This file defines all shared constants: cache thresholds, stakeholders, modules, OPCOs, Teams/ClickUp IDs, keyword triggers.

---

## ⛔ MEM0 IS RETIRED — v11.0

```
Mem0 skipped — Supabase is now the source of truth.
```

**Mem0 is fully decommissioned as of v11.0.**

- No reads from Mem0
- No writes to Mem0
- No atomic memory entries
- No tag scanning
- No fallback path to Mem0
- No mem0_list(), mem0_search(), mem0_add(), mem0_update(), mem0_delete()

**If any downstream skill or caller attempts a Mem0 operation, return:**

```
SKIPPED — Mem0 retired. Use Supabase helper instead.
See: upsert_knowledge_fact() / upsert_user_preference() / upsert_project_context()
```

**If Supabase is unavailable**, do NOT fall back to Mem0. Instead:
1. Log: `supabase_unavailable: <operation> <table>`
2. Print the exact SQL/JSON payload for manual insert (see Fallback Protocol below)
3. Mark output as `degraded=true`
4. Surface to user: "Supabase write failed — manual SQL payload below."

---

## VERSION CONTRACT

```python
UTILITY_VERSION = "11.2"
# Skills should log which version they last tested against.
# If you update any utility here, increment UTILITY_VERSION.
```

**Changelog:**

| 11.2 | **Loop v2 — outcome-aware learning (foundation)** (2026-06-14). New UTILITY 13: `capture_outcome_signals(since_ts)` — emits `outcome_signal` knowledge_facts for actions/risks reaching a terminal state, scoring each against the operator's earlier prediction (verdict: hit/over/under/neutral). Idempotent via fact_key `out:<kind>:<ref>`; NO new table/column (fact_type is free-text). Feeds calibration + rule-decay (omni-operator-learning — next gate) and is wired into omni-data-sync STEP 7 (next gate). Documented previously-undocumented learning fact_types (`operator_feedback`, `operator_rule`) in the knowledge_facts header. |
| 11.1 | **Feature Status Rollup** (2026-06-11). New `feature_status` table (DDL below) — entity layer keyed `(opco, feature)`; holds registry (label/aliases/registry_state) AND live rolled-up status. New UTILITY 12: `load_feature_registry_seed()` (bootstrap from omni-config §17, idempotent), `resolve_feature_key()` (tags NormalizedSignals), `rollup_feature_status()` (cross-source status reconciliation + auto-supersede per `FEATURE_AUTOSUPERSEDE`), `get_feature_rollup()` (reader). `build_context_pack_from_supabase()` returns new `feature_rollup` array. Reads omni-config v1.5 Section 17. |

| Version | Change |
|---|---|
| 11.2 | **Decision dedup render contract + version reconcile** (2026-06-21). `build_context_pack_from_supabase()` decisions query now filters `AND superseded_by IS NULL` so the duplicates merged by omni-data-sync v12.5 STEP 7A-DEDUP stop rendering in briefing/EOD packs (without this, the merge writes `superseded_by` but consumers still show both rows). Additive, non-destructive — no DDL. Also reconciled the stale `UTILITY_VERSION` annotations: the constant was already `11.2` while the description, an example comment, and omni-config §10 registry still read `11.1` (the handshake drift flagged by the weekly learning audit) — description + comment corrected here; omni-config registry bump (utils 11.1→11.2, data-sync 12.4→12.5, plus the other 4 stale rows) follows on approval. |
|---|---|
| 11.0 | **Supabase-ONLY mode** (2026-05-27). Mem0 fully retired — no reads, writes, or fallbacks. Removed all Mem0 helper functions (stubs remain to fail loudly). **Fix 1:** `actions.raw_json` column added via DDL — `write_action()` stores metadata there. **Fix 2:** `supabase_sql()` now raises on error instead of returning `None` — prevents write helpers from falsely reporting success. Every write helper catches the raised error and calls `_supabase_fallback_sql()`. **Fix 3:** `write_action()` action_key uses second-precision + 8-char summary hash (`YYYY-MM-DDTHH:MM:SS:<hash8>`) — prevents same-minute collision drops. **Fix 4:** `get_context_pack()` propagates `degraded` from `sb_pack.get("degraded", False)` — no longer hardcoded `False`. Freshness `status=partial` preserved when warnings exist. **Fix 5:** `upsert_decisions()` `VALID_STATUS` includes `rejected` — requires DB constraint DDL patch. **Fix 6:** `waiting_on_client` renamed to `client_facing_open_actions` in `build_context_pack_from_supabase()`. Legacy key preserved as alias. Future schema: `waiting_for` / `waiting_for_type` columns via DDL. **Fix 7:** RLS security note added — do not auto-enable. Added `upsert_knowledge_fact()`, `upsert_user_preference()`, `upsert_project_context()`. DDL for `knowledge_facts`, `user_preferences`, `project_context`. |
| 10.2 | **Idempotent upserts + duplicate audit**. `upsert_source_items` conflict key changed to `(source_type, external_id)`. Added `make_comment_external_id()`, `run_duplicate_audit()`. `upsert_decisions` enforces `status` enum at function level. `source_tags` added to `upsert_source_items`. |
| 10.1 | **`build_context_pack_from_supabase()` enriched fields**. All 6 secondary context pack fields guaranteed arrays. `waiting_on_client` / `waiting_on_team` tightened. `suggested_drafts` / `meetings_to_prepare` fully populated from Supabase. |
| 10.0 | **Supabase as PRIMARY structured cache**. Mem0 structured cache tags BLOCKED. New Supabase helpers added. Backward-compat wrappers with Mem0 fallback (now removed in v11.0). |

---

## HOW TO USE IN A CONSUMER SKILL

At the top of every skill's STEP 0:

```python
# Step 1: Read /mnt/skills/user/omni-config/SKILL.md  → CONFIG_VERSION = "1.2"
# Step 2: Read /mnt/skills/user/omni-utils/SKILL.md   → UTILITY_VERSION = "11.2"
#
# ⛔ MEM0 IS RETIRED. Do not call any Mem0 function.
#    Any Mem0 call returns: "SKIPPED — Mem0 retired. Use Supabase helper instead."
#
# Functions available:
#
#   Supabase core:
#     supabase_sql(query)
#
#   Sync lifecycle:
#     create_sync_run(), complete_sync_run(), get_latest_sync_run()
#
#   Structured data upserts:
#     upsert_source_items(), upsert_actions(), upsert_decisions(),
#     upsert_risks(), upsert_context_pack()
#
#   Action log (replaces Mem0 write_action):
#     write_action()  → writes to Supabase actions table
#
#   Knowledge / preference / project stores (NEW v11.0):
#     upsert_knowledge_fact()   → replaces [INTEL][*], [PATTERN], [PROJECT-DOC],
#                                  [COMM-STYLE], [PHRASEBOOK], [COMMITMENT][SENT],
#                                  [DECISION][SENT], [FOLLOW-UP][SENT], etc.
#     upsert_user_preference()  → replaces [STAKEHOLDER], [COMM-STYLE][GLOBAL],
#                                  [COMM-STYLE][STAKEHOLDER][*]
#     upsert_project_context()  → replaces [PROJECT-DOC][INDEX] + [PROJECT-DOC][file]
#
#   Context reads:
#     cache_check()             → Supabase only
#     get_context_pack()        → Supabase only
#     get_knowledge_facts()     → query knowledge_facts
#     get_user_preference()     → query user_preferences
#     get_project_docs()        → query project_context
#     build_context_pack_from_supabase()
#
#   Utility:
#     make_comment_external_id(), cleanup_old_raw_items(),
#     run_duplicate_audit(), cleanup_stale_knowledge_facts(),
#     diplomatic_mode()
#
#   External_id rules (upsert_source_items):
#     clickup_task    → ClickUp task ID  (e.g. '86exkz2rt')
#     clickup_comment → make_comment_external_id(...)
#     email           → message-id or Graph item ID
#     teams_message   → Teams message ID
#     calendar_event  → Graph event ID
#     ado_work_item   → ADO work item ID as string
```

---

## ⛔ MEM0 GUARDRAIL FUNCTION

Any skill that still calls a Mem0 function must receive this response immediately:

```python
def _mem0_retired(fn_name: str) -> str:
    """
    Hard guardrail: called by any stub of a retired Mem0 function.
    Returns a visible error string and prints a log.
    Never silently no-ops — always surfaces the call so the skill author knows to fix it.
    """
    msg = (
        f"SKIPPED — Mem0 retired (fn={fn_name}). "
        f"Use Supabase helper instead: "
        f"upsert_knowledge_fact() / upsert_user_preference() / upsert_project_context() / write_action()"
    )
    print(f"[mem0_guardrail] {msg}")
    return msg

# Stub shims — do not remove these until all downstream skills are updated to v11.0
# They prevent silent failures when an outdated skill calls a retired function.

def mem0_list(*args, **kwargs):    return _mem0_retired("mem0_list")
def mem0_search(*args, **kwargs):  return _mem0_retired("mem0_search")
def mem0_add(*args, **kwargs):     return _mem0_retired("mem0_add")
def mem0_update(*args, **kwargs):  return _mem0_retired("mem0_update")
def mem0_delete(*args, **kwargs):  return _mem0_retired("mem0_delete")

def write_structured_cache_verbatim(*args, **kwargs):
    return _mem0_retired("write_structured_cache_verbatim")

def verify_structured_cache_integrity(*args, **kwargs):
    return _mem0_retired("verify_structured_cache_integrity")

def read_cache_by_metadata(*args, **kwargs):
    return _mem0_retired("read_cache_by_metadata")

def mem0_health_check(*args, **kwargs):
    return _mem0_retired("mem0_health_check")

def _get_context_pack_legacy(*args, **kwargs):
    return _mem0_retired("_get_context_pack_legacy")

def is_mem0_write_blocked(*args, **kwargs):
    return _mem0_retired("is_mem0_write_blocked")
```

---

## DDL — REQUIRED TABLES (v11.0)

Run these migrations before upgrading skills to v11.0.

### knowledge_facts

Replaces all atomic Mem0 tags: `[INTEL][*]`, `[PATTERN]`, `[COMM-STYLE]`, `[PHRASEBOOK]`, `[COMMITMENT][SENT]`, `[DECISION][SENT]`, `[FOLLOW-UP][SENT]`, `[THREAD-INTEL][EMAIL]`, `[STAKEHOLDER-PATTERN]`, `[PROJECT-PATTERN]`, `[ACTION][REQ]`.

```sql
CREATE TABLE IF NOT EXISTS knowledge_facts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- Classification
  fact_type       TEXT NOT NULL,
  -- Allowed values:
  --   'intel_daily'         ← replaces [INTEL][DAILY][date]
  --   'intel_weekly'        ← replaces [INTEL][WEEKLY][week]
  --   'intel_pattern'       ← replaces [INTEL][PATTERN][topic] and [PATTERN]
  --   'intel_risk'          ← replaces [INTEL][RISK] entries
  --   'intel_decision'      ← replaces [INTEL][DECISION] entries
  --   'phrasebook'          ← replaces [PHRASEBOOK][USER]
  --   'commitment'          ← replaces [COMMITMENT][SENT]
  --   'decision_sent'       ← replaces [DECISION][SENT]
  --   'follow_up'           ← replaces [FOLLOW-UP][SENT]
  --   'thread_intel'        ← replaces [THREAD-INTEL][EMAIL]
  --   'stakeholder_pattern' ← replaces [STAKEHOLDER-PATTERN][Name]
  --   'project_pattern'     ← replaces [PROJECT-PATTERN][Module]
  --   'action_req'          ← replaces [ACTION][REQ] entries
  --   'outcome_signal'      ← Loop v2: action/risk terminal-state outcome vs prediction (verdict)
  --   'operator_feedback'   ← learning: captured user correction (omni-operator-learning)
  --   'operator_rule'       ← learning: promoted prevention rule (injected at briefing/EOD STEP 0A2)

  fact_key        TEXT NOT NULL,          -- unique dedup key: '<type>:<scope>:<date_or_id>'
                                          -- e.g. 'intel_daily:global:2026-05-27'
                                          --      'intel_pattern:global:loop-qa-delay'
                                          --      'commitment:global:v3'
                                          --      'stakeholder_pattern:Andrea:v2'

  scope           TEXT,                   -- stakeholder name, module, opco, or 'global'
  content         JSONB NOT NULL,         -- structured payload (replaces free-text Mem0 blob)
  source_skill    TEXT,                   -- skill that wrote this entry
  source_sync_id  UUID REFERENCES sync_runs(id) ON DELETE SET NULL,
  tags            TEXT[],                 -- optional searchable tags
  fingerprints    TEXT[],                 -- dedup fps (for commitment/sent tracking)
  version         INT NOT NULL DEFAULT 1,
  status          TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'archived', 'resolved', 'closed')),
  expires_at      TIMESTAMPTZ,            -- null = never expires
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE (fact_type, fact_key)
);

CREATE INDEX IF NOT EXISTS idx_kf_type    ON knowledge_facts(fact_type);
CREATE INDEX IF NOT EXISTS idx_kf_scope   ON knowledge_facts(scope);
CREATE INDEX IF NOT EXISTS idx_kf_status  ON knowledge_facts(status);
CREATE INDEX IF NOT EXISTS idx_kf_updated ON knowledge_facts(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_kf_expires ON knowledge_facts(expires_at)
    WHERE expires_at IS NOT NULL;
```

### user_preferences

Replaces: `[STAKEHOLDER]`, `[COMM-STYLE][GLOBAL]`, `[COMM-STYLE][STAKEHOLDER][*]`.

```sql
CREATE TABLE IF NOT EXISTS user_preferences (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  pref_type     TEXT NOT NULL,
  -- Allowed values:
  --   'comm_style_global'   ← replaces [COMM-STYLE][GLOBAL]
  --   'stakeholder_profile' ← replaces [COMM-STYLE][STAKEHOLDER][Name] and [STAKEHOLDER]
  --   'operator_setting'    ← operational settings (thresholds, flags)

  pref_key      TEXT NOT NULL,   -- e.g. 'nghiem:global', 'nghiem:Andrea', 'nghiem:YiLun'
  content       JSONB NOT NULL,  -- structured preference payload
  source_skill  TEXT,
  version       INT NOT NULL DEFAULT 1,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE (pref_type, pref_key)
);

CREATE INDEX IF NOT EXISTS idx_up_type ON user_preferences(pref_type);
CREATE INDEX IF NOT EXISTS idx_up_key  ON user_preferences(pref_key);
```

### project_context

Replaces: `[PROJECT-DOC][INDEX]` and `[PROJECT-DOC][filename_stem]` entries.

```sql
CREATE TABLE IF NOT EXISTS project_context (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  file_stem     TEXT NOT NULL UNIQUE,     -- e.g. 'OMNIHighLevel', 'REPCustomer360Toolkit'
  file_path     TEXT NOT NULL,
  file_hash     TEXT NOT NULL,            -- MD5 for change detection
  module        TEXT,                     -- e.g. 'REP', 'OMNI', 'HAP'
  slide_count   INT,
  key_topics    TEXT[],
  module_coverage TEXT[],
  feature_highlights TEXT[],
  architecture_notes TEXT[],
  slide_index   JSONB,                    -- {slide_num: title/summary}
  indexed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pc_module ON project_context(module);
```

### feature_status (v11.1)

Entity layer: one row per `(OPCO, Feature)`. Holds BOTH the registry (label, aliases,
registry_state) and the live rolled-up status. Dedicated table justified: mutable
operational state is out of scope for `knowledge_facts` (durable facts only) and
needs structured filtering by opco/module/status plus joins to source tables.

```sql
CREATE TABLE IF NOT EXISTS feature_status (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  feature_key        TEXT NOT NULL UNIQUE,        -- '<OPCO>:<feature-slug>' e.g. 'MM:customer-module'
  opco               TEXT NOT NULL,               -- MY|ID|KH|LA|TW|IN|MM|ALL
  module             TEXT,                        -- REP|LOOP|HAP|PEM|OMS|CC|OMNI
  label              TEXT NOT NULL,               -- display name e.g. 'MM Customer Module'
  aliases            TEXT[] NOT NULL DEFAULT '{}',-- match keywords; auto-learned over time
  registry_state     TEXT NOT NULL DEFAULT 'seeded',  -- seeded|confirmed|candidate|rejected
  status             TEXT NOT NULL DEFAULT 'unknown', -- deployed|decided|incident|blocked|at_risk|in_progress|planned|done|unknown
  status_signal      TEXT,                        -- DEPLOY|DECISION|INCIDENT|BLOCKER|URGENT|APPROVAL|DIRECTION
  status_source      TEXT,                        -- EMAIL|TEAMS|CLICKUP|ADO
  status_source_ref  TEXT,                        -- source_items.external_id of the deciding signal
  status_actor       TEXT,                        -- who set the latest status
  status_summary     TEXT,                        -- ≤25w summary of deciding signal
  status_updated_at  TIMESTAMPTZ,                 -- ts of the deciding signal
  evidence           JSONB DEFAULT '[]',          -- last ≤10 supporting signal refs (all sources)
  conflicts          JSONB DEFAULT '[]',          -- lower-confidence contradicting signals awaiting review
  open_counts        JSONB DEFAULT '{}',          -- {"actions":N,"risks":N,"clickup":N} snapshot
  superseded_actions JSONB DEFAULT '[]',          -- audit: action_keys auto-superseded by this feature
  signal_count       INT NOT NULL DEFAULT 0,      -- total linked signals (auto-discovery threshold)
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fs_opco    ON feature_status(opco);
CREATE INDEX IF NOT EXISTS idx_fs_module  ON feature_status(module);
CREATE INDEX IF NOT EXISTS idx_fs_status  ON feature_status(status);
CREATE INDEX IF NOT EXISTS idx_fs_state   ON feature_status(registry_state);

-- source_items gains feature_key for signal→feature linkage
ALTER TABLE public.source_items ADD COLUMN IF NOT EXISTS feature_key TEXT;
CREATE INDEX IF NOT EXISTS idx_si_feature ON source_items(feature_key);

-- actions gains feature_key for supersede targeting
ALTER TABLE public.actions ADD COLUMN IF NOT EXISTS feature_key TEXT;
CREATE INDEX IF NOT EXISTS idx_ac_feature ON actions(feature_key);
```

---

## SUPABASE CONNECTION

```python
SUPABASE_PROJECT_ID = "upuzblwjxvmlrkokeqal"
SUPABASE_URL        = "https://upuzblwjxvmlrkokeqal.supabase.co"

# All Supabase operations go through the Supabase MCP tools:
#   Supabase:execute_sql(project_id, query)
# Never call Supabase REST API directly from skills.
# Never hardcode credentials — MCP handles auth.
# DDL / schema changes → Supabase.apply_migration() only, never execute_sql().
```

---

## SUPABASE FALLBACK PROTOCOL

When Supabase is unavailable (any write fails):

```python
def _supabase_fallback_sql(table: str, key_field: str, key_value: str, payload: dict) -> None:
    """
    When Supabase write fails, print exact SQL for manual insert.
    Never write to Mem0. Never silently drop the data.
    """
    import json
    print(f"\n{'='*60}")
    print(f"⚠️  SUPABASE WRITE FAILED — MANUAL INSERT REQUIRED")
    print(f"Table: {table} | Key: {key_field}={key_value}")
    print(f"Payload JSON:\n{json.dumps(payload, indent=2, default=str)}")
    print(f"{'='*60}\n")
```

---

## SUPABASE CORE LAYER

### `supabase_sql()` — low-level wrapper

```python
def supabase_sql(query: str) -> list:
    """
    Execute a SQL query via Supabase MCP.
    Returns list of row dicts on success.
    RAISES on error — callers must catch and call _supabase_fallback_sql().
    Never silently returns None — a silent None causes write helpers to falsely
    report success when the DB write never happened.
    Never use for DDL — use Supabase.apply_migration() for schema changes.
    """
    try:
        result = Supabase.execute_sql(
            project_id=SUPABASE_PROJECT_ID,
            query=query
        )
        if result and "result" in result:
            import json, re
            raw = result["result"]
            match = re.search(r'\[.*\]', raw, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        return []
    except Exception as e:
        print(f"[supabase_sql] ERROR: {e}")
        raise  # ← callers catch this and call _supabase_fallback_sql()
```

---

## UTILITY 1 — `write_action()`

**v11.0: Writes to Supabase `actions` table. Mem0 is NOT used.**

**Required DDL** — run once before upgrading skills to v11.0:
```sql
-- Fix 1: actions table does not have raw_json by default
ALTER TABLE public.actions
ADD COLUMN IF NOT EXISTS raw_json jsonb;
```

```python
def write_action(
    skill: str,
    action_type: str,
    summary: str,
    metadata: dict = None,
    sync_id: str = None,
    owner: str = "Nghiem",
    priority: str = "P2",
    status: str = "open",
    module: str = None,
    market: str = None,
) -> bool:
    """
    Write a structured action log entry to Supabase actions table.

    v11.0 CHANGE: Previously wrote [ACTION][skill][date] to Mem0.
    Now writes a row to the Supabase `actions` table.
    Mem0 is NOT used. No fallback to Mem0.

    action_key format (Fix 3 — second-precision + summary hash to prevent same-minute collisions):
      'action:<skill>:<action_type>:<YYYY-MM-DDTHH:MM:SS>:<hash8>'
    ON CONFLICT (action_key) DO NOTHING — intentional: duplicate keys = same logical event.

    Returns True on success, False on failure.
    On failure: prints fallback SQL payload for manual insert.

    skill:       one of ACTION_VALID_SKILLS from omni-config
    action_type: one of ACTION_VALID_TYPES from omni-config
    summary:     ≤200 chars description
    metadata:    optional dict of key-value pairs (stored in raw_json)
    sync_id:     optional — link to sync_runs row
    owner:       default 'Nghiem'
    priority:    default 'P2'
    status:      default 'open'
    module:      optional module context
    market:      optional market context
    """
    from datetime import datetime, timezone, timedelta
    import json, hashlib

    gmt7     = timezone(timedelta(hours=7))
    now      = datetime.now(gmt7)
    ts_str   = now.strftime("%Y-%m-%d %H:%M GMT+7")
    date_str = now.strftime("%Y-%m-%d")

    # Fix 3: second-precision + summary hash prevents same-minute key collisions
    summary_hash = hashlib.md5(summary.encode()).hexdigest()[:8]
    action_key   = f"action:{skill}:{action_type}:{now.strftime('%Y-%m-%dT%H:%M:%S')}:{summary_hash}"
    title        = f"[{skill}] {action_type}: {summary[:160]}"

    # Fix 1: metadata stored in raw_json (column added via DDL above)
    raw = {"skill": skill, "action_type": action_type, "summary": summary, "ts": ts_str}
    if metadata:
        raw.update(metadata)

    def esc(v):
        if v is None: return "NULL"
        return "'" + str(v).replace("'", "''") + "'"

    def esc_json(v):
        if v is None: return "NULL"
        return "'" + json.dumps(v).replace("'", "''") + "'::jsonb"

    sync_sql = f"'{sync_id}'::uuid" if sync_id else "NULL"

    query = f"""
    INSERT INTO actions (
        sync_id, run_date, action_key, title, owner, source,
        source_ref, module, market, priority, status, raw_json
    ) VALUES (
        {sync_sql}, '{date_str}',
        {esc(action_key)},
        {esc(title)},
        {esc(owner)},
        {esc(skill)},
        {esc(action_type)},
        {esc(module)},
        {esc(market)},
        {esc(priority)},
        {esc(status)},
        {esc_json(raw)}
    )
    ON CONFLICT (action_key) DO NOTHING;
    """

    try:
        supabase_sql(query)  # raises on DB error (Fix 2)
        print(f"[write_action] supabase_action_written: skill={skill} type={action_type} key={action_key}")
        return True
    except Exception as e:
        print(f"[write_action] FAILED: {e}")
        _supabase_fallback_sql("actions", "action_key", action_key, {
            "action_key": action_key, "title": title, "owner": owner,
            "source": skill, "source_ref": action_type, "priority": priority,
            "status": status, "raw_json": raw
        })
        return False
```

---

## UTILITY 2 — `upsert_knowledge_fact()`

Replaces all atomic Mem0 tag writes: `[INTEL][*]`, `[PATTERN]`, `[COMM-STYLE]`, `[PHRASEBOOK]`, `[COMMITMENT][SENT]`, `[DECISION][SENT]`, `[FOLLOW-UP][SENT]`, `[THREAD-INTEL][EMAIL]`, `[STAKEHOLDER-PATTERN]`, `[PROJECT-PATTERN]`, `[ACTION][REQ]`.

```python
def upsert_knowledge_fact(
    fact_type: str,
    fact_key: str,
    content: dict,
    scope: str = None,
    source_skill: str = None,
    sync_id: str = None,
    tags: list = None,
    fingerprints: list = None,
    status: str = "active",
    expires_at: str = None,
) -> bool:
    """
    Upsert a single knowledge fact into Supabase knowledge_facts table.

    Replaces ALL atomic Mem0 writes (see fact_type values in DDL above).

    fact_type: see DDL — 'intel_daily', 'intel_weekly', 'intel_pattern',
               'intel_risk', 'intel_decision', 'phrasebook', 'commitment',
               'decision_sent', 'follow_up', 'thread_intel',
               'stakeholder_pattern', 'project_pattern', 'action_req'

    fact_key:  stable dedup key — format '<type>:<scope>:<date_or_id>'
               e.g. 'intel_daily:global:2026-05-27'
               e.g. 'stakeholder_pattern:Andrea:v5'
               e.g. 'commitment:global:v3'

    content:   dict — the structured payload (what was previously a Mem0 text blob)
    scope:     stakeholder name, module, opco, or 'global'
    fingerprints: list of email fingerprint strings (for commitment/sent dedup)
    expires_at: ISO timestamp or None (auto-set for intel_daily=60d, intel_weekly=90d)

    Returns True on success.
    On failure: prints fallback SQL for manual insert. Does NOT write to Mem0.
    Logs: supabase_knowledge_fact_upserted | supabase_knowledge_fact_failed
    """
    from datetime import datetime, timezone, timedelta
    import json

    gmt7 = timezone(timedelta(hours=7))
    now  = datetime.now(gmt7)

    # Auto-compute expires_at if not provided
    if expires_at is None:
        if fact_type == "intel_daily":
            expires_at = (now + timedelta(days=60)).isoformat()
        elif fact_type == "intel_weekly":
            expires_at = (now + timedelta(days=90)).isoformat()
        # All other types: no expiry (None = never expires)

    def esc(v):
        if v is None: return "NULL"
        return "'" + str(v).replace("'", "''") + "'"

    def esc_json(v):
        if v is None: return "NULL"
        return "'" + json.dumps(v).replace("'", "''") + "'::jsonb"

    def esc_arr(v):
        if not v: return "ARRAY[]::text[]"
        return "ARRAY[" + ",".join(f"'{str(x).replace(chr(39), chr(39)*2)}'" for x in v) + "]"

    sync_sql = f"'{sync_id}'::uuid" if sync_id else "NULL"

    query = f"""
    INSERT INTO knowledge_facts (
        fact_type, fact_key, scope, content, source_skill,
        source_sync_id, tags, fingerprints, status, expires_at
    ) VALUES (
        {esc(fact_type)},
        {esc(fact_key)},
        {esc(scope)},
        {esc_json(content)},
        {esc(source_skill)},
        {sync_sql},
        {esc_arr(tags)},
        {esc_arr(fingerprints)},
        {esc(status)},
        {esc(expires_at)}
    )
    ON CONFLICT (fact_type, fact_key) DO UPDATE SET
        scope        = COALESCE(EXCLUDED.scope, knowledge_facts.scope),
        content      = EXCLUDED.content,
        source_skill = EXCLUDED.source_skill,
        source_sync_id = COALESCE(EXCLUDED.source_sync_id, knowledge_facts.source_sync_id),
        tags         = EXCLUDED.tags,
        fingerprints = EXCLUDED.fingerprints,
        status       = EXCLUDED.status,
        expires_at   = EXCLUDED.expires_at,
        version      = knowledge_facts.version + 1,
        updated_at   = NOW();
    """

    try:
        supabase_sql(query)
        print(f"[upsert_knowledge_fact] supabase_knowledge_fact_upserted: type={fact_type} key={fact_key}")
        return True
    except Exception as e:
        print(f"[upsert_knowledge_fact] supabase_knowledge_fact_failed: {e}")
        _supabase_fallback_sql("knowledge_facts", "fact_key", fact_key, {
            "fact_type": fact_type, "fact_key": fact_key, "scope": scope,
            "content": content, "source_skill": source_skill, "status": status,
            "expires_at": expires_at
        })
        return False
```

### `get_knowledge_facts()` — read helper

```python
def get_knowledge_facts(
    fact_type: str,
    scope: str = None,
    status: str = "active",
    limit: int = 20,
    include_expired: bool = False,
) -> list:
    """
    Query knowledge_facts by type (and optionally scope).
    Returns list of row dicts with content parsed as dict.

    fact_type:       required — e.g. 'intel_daily', 'stakeholder_pattern'
    scope:           optional — filter by scope (stakeholder, module, 'global')
    status:          default 'active'
    include_expired: if False (default), excludes rows where expires_at < NOW()
    """
    scope_filter   = f"AND scope = '{scope.replace(chr(39), chr(39)*2)}'" if scope else ""
    expiry_filter  = "" if include_expired else "AND (expires_at IS NULL OR expires_at > NOW())"
    status_filter  = f"AND status = '{status}'" if status else ""

    query = f"""
    SELECT id::text, fact_type, fact_key, scope, content,
           source_skill, tags, fingerprints, version, status,
           expires_at::text, created_at::text, updated_at::text
    FROM knowledge_facts
    WHERE fact_type = '{fact_type}'
      {status_filter}
      {scope_filter}
      {expiry_filter}
    ORDER BY updated_at DESC
    LIMIT {limit};
    """
    rows = supabase_sql(query) or []
    print(f"[get_knowledge_facts] type={fact_type} scope={scope} rows={len(rows)}")
    return rows
```

---

## UTILITY 3 — `upsert_user_preference()`

Replaces `[COMM-STYLE][GLOBAL]`, `[COMM-STYLE][STAKEHOLDER][*]`, `[STAKEHOLDER]` in Mem0.

```python
def upsert_user_preference(
    pref_type: str,
    pref_key: str,
    content: dict,
    source_skill: str = None,
) -> bool:
    """
    Upsert a user preference into Supabase user_preferences table.

    pref_type:
      'comm_style_global'   — global communication style profile (was [COMM-STYLE][GLOBAL])
      'stakeholder_profile' — per-stakeholder style/preference (was [COMM-STYLE][STAKEHOLDER][Name])
      'operator_setting'    — operational settings/flags

    pref_key:
      'nghiem:global'       — for comm_style_global
      'nghiem:<name>'       — for stakeholder_profile, e.g. 'nghiem:Andrea', 'nghiem:YiLun'
      'nghiem:<setting>'    — for operator_setting

    content: structured dict — the preference payload

    Returns True on success.
    On failure: prints fallback SQL. Does NOT write to Mem0.
    Logs: supabase_user_pref_upserted | supabase_user_pref_failed
    """
    import json

    def esc(v):
        if v is None: return "NULL"
        return "'" + str(v).replace("'", "''") + "'"

    def esc_json(v):
        if v is None: return "NULL"
        return "'" + json.dumps(v).replace("'", "''") + "'::jsonb"

    query = f"""
    INSERT INTO user_preferences (pref_type, pref_key, content, source_skill)
    VALUES ({esc(pref_type)}, {esc(pref_key)}, {esc_json(content)}, {esc(source_skill)})
    ON CONFLICT (pref_type, pref_key) DO UPDATE SET
        content      = EXCLUDED.content,
        source_skill = EXCLUDED.source_skill,
        version      = user_preferences.version + 1,
        updated_at   = NOW();
    """

    try:
        supabase_sql(query)
        print(f"[upsert_user_preference] supabase_user_pref_upserted: type={pref_type} key={pref_key}")
        return True
    except Exception as e:
        print(f"[upsert_user_preference] supabase_user_pref_failed: {e}")
        _supabase_fallback_sql("user_preferences", "pref_key", pref_key, {
            "pref_type": pref_type, "pref_key": pref_key, "content": content
        })
        return False


def get_user_preference(pref_type: str, pref_key: str) -> dict | None:
    """
    Fetch a single user preference row by type + key.
    Returns row dict or None if not found.
    """
    def esc(v):
        return "'" + str(v).replace("'", "''") + "'"

    query = f"""
    SELECT id::text, pref_type, pref_key, content,
           source_skill, version, updated_at::text
    FROM user_preferences
    WHERE pref_type = {esc(pref_type)}
      AND pref_key  = {esc(pref_key)}
    LIMIT 1;
    """
    rows = supabase_sql(query)
    return rows[0] if rows else None


def list_user_preferences(pref_type: str) -> list:
    """
    List all preferences of a given type.
    Returns list of row dicts.
    """
    def esc(v):
        return "'" + str(v).replace("'", "''") + "'"

    query = f"""
    SELECT id::text, pref_type, pref_key, content,
           source_skill, version, updated_at::text
    FROM user_preferences
    WHERE pref_type = {esc(pref_type)}
    ORDER BY updated_at DESC;
    """
    return supabase_sql(query) or []
```

---

## UTILITY 4 — `upsert_project_context()`

Replaces `[PROJECT-DOC][INDEX]` and `[PROJECT-DOC][filename_stem]` Mem0 entries.

```python
def upsert_project_context(
    file_stem: str,
    file_path: str,
    file_hash: str,
    module: str = None,
    slide_count: int = None,
    key_topics: list = None,
    module_coverage: list = None,
    feature_highlights: list = None,
    architecture_notes: list = None,
    slide_index: dict = None,
) -> bool:
    """
    Upsert a project reference doc index entry into Supabase project_context table.

    Replaces [PROJECT-DOC][filename_stem] Mem0 entries.
    Replaces [PROJECT-DOC][INDEX] — the index is now the project_context table itself.

    file_stem:  unique identifier, e.g. 'OMNIHighLevel', 'REPCustomer360Toolkit'
    file_hash:  MD5 of the file content for change detection
    module:     e.g. 'REP', 'OMNI', 'HAP', 'LOOP'

    Returns True on success.
    On failure: prints fallback SQL. Does NOT write to Mem0.
    Logs: supabase_project_context_upserted | supabase_project_context_failed
    """
    import json

    def esc(v):
        if v is None: return "NULL"
        return "'" + str(v).replace("'", "''") + "'"

    def esc_arr(v):
        if not v: return "ARRAY[]::text[]"
        return "ARRAY[" + ",".join(f"'{str(x).replace(chr(39), chr(39)*2)}'" for x in v) + "]"

    def esc_json(v):
        if v is None: return "NULL"
        return "'" + json.dumps(v).replace("'", "''") + "'::jsonb"

    sc_sql = str(slide_count) if slide_count is not None else "NULL"

    query = f"""
    INSERT INTO project_context (
        file_stem, file_path, file_hash, module, slide_count,
        key_topics, module_coverage, feature_highlights, architecture_notes, slide_index
    ) VALUES (
        {esc(file_stem)}, {esc(file_path)}, {esc(file_hash)},
        {esc(module)}, {sc_sql},
        {esc_arr(key_topics)}, {esc_arr(module_coverage)},
        {esc_arr(feature_highlights)}, {esc_arr(architecture_notes)},
        {esc_json(slide_index)}
    )
    ON CONFLICT (file_stem) DO UPDATE SET
        file_path          = EXCLUDED.file_path,
        file_hash          = EXCLUDED.file_hash,
        module             = COALESCE(EXCLUDED.module, project_context.module),
        slide_count        = COALESCE(EXCLUDED.slide_count, project_context.slide_count),
        key_topics         = EXCLUDED.key_topics,
        module_coverage    = EXCLUDED.module_coverage,
        feature_highlights = EXCLUDED.feature_highlights,
        architecture_notes = EXCLUDED.architecture_notes,
        slide_index        = EXCLUDED.slide_index,
        updated_at         = NOW();
    """

    try:
        supabase_sql(query)
        print(f"[upsert_project_context] supabase_project_context_upserted: file={file_stem}")
        return True
    except Exception as e:
        print(f"[upsert_project_context] supabase_project_context_failed: {e}")
        _supabase_fallback_sql("project_context", "file_stem", file_stem, {
            "file_stem": file_stem, "file_path": file_path, "file_hash": file_hash,
            "module": module
        })
        return False


def get_project_docs(file_stem: str = None) -> list:
    """
    Query project_context. Pass file_stem for single-doc lookup, or None for all docs.
    Replaces [PROJECT-DOC][INDEX] Mem0 scan.
    Returns list of row dicts.
    """
    if file_stem:
        where = f"WHERE file_stem = '{file_stem.replace(chr(39), chr(39)*2)}'"
    else:
        where = ""

    query = f"""
    SELECT file_stem, file_path, file_hash, module, slide_count,
           key_topics, module_coverage, feature_highlights,
           architecture_notes, slide_index, indexed_at::text, updated_at::text
    FROM project_context
    {where}
    ORDER BY updated_at DESC;
    """
    return supabase_sql(query) or []
```

---

## UTILITY 5 — Supabase Sync Run Helpers

### `create_sync_run()`

```python
def create_sync_run(
    sync_type: str,
    window_start: str = None,
    window_end: str = None,
    sources_ok: list = None,
    sources_failed: list = None,
    summary: str = None,
) -> str | None:
    """
    Insert a new sync_run row with status='running'.
    Returns the UUID string of the new row, or None on error.
    Logs: supabase_sync_run_created
    """
    from datetime import datetime, timezone, timedelta
    import json

    gmt7     = timezone(timedelta(hours=7))
    run_date = datetime.now(gmt7).strftime("%Y-%m-%d")

    ok_arr   = "ARRAY[" + ",".join(f"'{s}'" for s in (sources_ok or [])) + "]"
    fail_arr = "ARRAY[" + ",".join(f"'{s}'" for s in (sources_failed or [])) + "]"
    ws       = f"'{window_start}'" if window_start else "NULL"
    we       = f"'{window_end}'"   if window_end   else "NULL"
    sm       = f"'{summary.replace(chr(39), chr(39)*2)}'" if summary else "NULL"

    query = f"""
    INSERT INTO sync_runs (sync_type, run_date, window_start, window_end,
                           status, sources_ok, sources_failed, summary)
    VALUES ('{sync_type}', '{run_date}', {ws}, {we},
            'running', {ok_arr}, {fail_arr}, {sm})
    RETURNING id::text;
    """
    rows = supabase_sql(query)
    if rows and len(rows) > 0:
        sync_id = rows[0].get("id")
        print(f"[create_sync_run] supabase_sync_run_created: id={sync_id} type={sync_type}")
        return sync_id
    print(f"[create_sync_run] ERROR: no id returned")
    return None
```

### `complete_sync_run()`

```python
def complete_sync_run(
    sync_id: str,
    status: str = "complete",
    sources_ok: list = None,
    sources_failed: list = None,
    summary: str = None,
) -> bool:
    """
    Update sync_run status to complete | failed.
    Returns True on success.
    Logs: supabase_sync_run_completed
    """
    ok_arr   = "ARRAY[" + ",".join(f"'{s}'" for s in (sources_ok or [])) + "]"
    fail_arr = "ARRAY[" + ",".join(f"'{s}'" for s in (sources_failed or [])) + "]"
    sm       = f"'{summary.replace(chr(39), chr(39)*2)}'" if summary else "NULL"

    query = f"""
    UPDATE sync_runs
    SET status = '{status}',
        sources_ok = {ok_arr},
        sources_failed = {fail_arr},
        summary = {sm}
    WHERE id = '{sync_id}'::uuid;
    """
    supabase_sql(query)
    print(f"[complete_sync_run] supabase_sync_run_completed: id={sync_id} status={status}")
    return True
```

### `get_latest_sync_run()`

```python
def get_latest_sync_run() -> dict | None:
    """
    Returns the most recent sync_run row (complete or running).
    """
    query = """
    SELECT id::text, sync_type, run_at::text, run_date::text,
           window_start::text, window_end::text, status,
           sources_ok, sources_failed, summary
    FROM sync_runs
    ORDER BY run_at DESC
    LIMIT 1;
    """
    rows = supabase_sql(query)
    return rows[0] if rows else None
```

---

## UTILITY 6 — Upsert Source Items and Structured Data

### `make_comment_external_id()` — stable dedup key for ClickUp comments

```python
def make_comment_external_id(
    comment_id: str | None,
    task_id: str,
    created_at: str,
    author: str,
    comment_text: str,
) -> str:
    """
    Returns a stable external_id for a ClickUp comment.
    Priority:
    1. Use comment_id directly if available.
    2. Fallback: deterministic hash — task_id + created_at + author + hash4(text).
    """
    if comment_id:
        return str(comment_id)
    import hashlib
    text_hash = hashlib.md5((comment_text or "").encode()).hexdigest()[:8]
    return f"cu-comment-{task_id}-{created_at}-{author}-{text_hash}"
```

### `upsert_source_items()`

```python
def upsert_source_items(sync_id: str, items: list) -> int:
    """
    Batch upsert a list of source item dicts into source_items.
    Conflict key: UNIQUE (source_type, external_id)

    external_id rules (caller must set correctly):
      clickup_task    → ClickUp task ID         e.g. '86exkz2rt'
      clickup_comment → make_comment_external_id() result
      email           → message-id or Graph item ID
      teams_message   → Teams message ID
      calendar_event  → Graph event ID
      ado_work_item   → ADO work item ID (int as str)

    Each item dict keys:
        external_id (REQUIRED), source_type (REQUIRED), item_id,
        title, summary, body_excerpt, source_url, sender, tags, source_tags,
        market, module, priority, status, assignee, due_date,
        is_urgent, is_client_facing, raw_json, item_created_at, item_updated_at

    Returns: count of rows upserted.
    Logs: supabase_source_items_upserted
    """
    from datetime import datetime, timezone, timedelta
    import json

    if not items:
        return 0

    gmt7     = timezone(timedelta(hours=7))
    run_date = datetime.now(gmt7).strftime("%Y-%m-%d")

    def esc(v):
        if v is None: return "NULL"
        return "'" + str(v).replace("'", "''") + "'"

    def esc_bool(v):
        return "true" if v else "false"

    def esc_arr(v):
        if not v: return "ARRAY[]::text[]"
        return "ARRAY[" + ",".join(f"'{str(x).replace(chr(39), chr(39)*2)}'" for x in v) + "]"

    def esc_json(v):
        if not v: return "NULL"
        return "'" + json.dumps(v).replace("'", "''") + "'::jsonb"

    rows_sql = []
    skipped  = 0
    for item in items:
        ext_id = item.get("external_id") or item.get("item_id")
        if not ext_id:
            print(f"[upsert_source_items] WARNING: skipping item with no external_id: {item.get('title','?')}")
            skipped += 1
            continue
        item_id = item.get("item_id") or ext_id
        rows_sql.append(f"""(
            '{sync_id}'::uuid, '{run_date}',
            {esc(item.get('source_type'))},
            {esc(ext_id)},
            {esc(item_id)},
            {esc(item.get('title'))},
            {esc(item.get('summary'))},
            {esc(item.get('body_excerpt'))},
            {esc(item.get('source_url'))},
            {esc(item.get('sender'))},
            {esc_arr(item.get('tags'))},
            {esc_arr(item.get('source_tags'))},
            {esc(item.get('market'))},
            {esc(item.get('module'))},
            {esc(item.get('priority'))},
            {esc(item.get('status'))},
            {esc(item.get('assignee'))},
            {esc(item.get('due_date'))},
            {esc_bool(item.get('is_urgent', False))},
            {esc_bool(item.get('is_client_facing', False))},
            {esc_json(item.get('raw_json'))},
            {esc(item.get('item_created_at'))},
            {esc(item.get('item_updated_at'))}
        )""")

    if not rows_sql:
        print(f"[upsert_source_items] WARNING: 0 rows to upsert after validation (skipped={skipped})")
        return 0

    values = ",\n".join(rows_sql)
    query = f"""
    INSERT INTO source_items (
        sync_id, run_date, source_type, external_id, item_id,
        title, summary, body_excerpt, source_url, sender,
        tags, source_tags, market, module, priority, status, assignee,
        due_date, is_urgent, is_client_facing, raw_json,
        item_created_at, item_updated_at
    ) VALUES {values}
    ON CONFLICT (source_type, external_id) DO UPDATE SET
        sync_id          = EXCLUDED.sync_id,
        run_date         = EXCLUDED.run_date,
        item_id          = EXCLUDED.item_id,
        title            = EXCLUDED.title,
        summary          = EXCLUDED.summary,
        body_excerpt     = EXCLUDED.body_excerpt,
        source_url       = EXCLUDED.source_url,
        sender           = EXCLUDED.sender,
        tags             = EXCLUDED.tags,
        source_tags      = EXCLUDED.source_tags,
        market           = EXCLUDED.market,
        module           = EXCLUDED.module,
        priority         = EXCLUDED.priority,
        status           = EXCLUDED.status,
        assignee         = EXCLUDED.assignee,
        due_date         = EXCLUDED.due_date,
        is_urgent        = EXCLUDED.is_urgent,
        is_client_facing = EXCLUDED.is_client_facing,
        raw_json         = COALESCE(EXCLUDED.raw_json, source_items.raw_json),
        item_updated_at  = EXCLUDED.item_updated_at,
        synced_at        = now();
    """
    supabase_sql(query)
    n = len(rows_sql)
    print(f"[upsert_source_items] supabase_source_items_upserted: count={n} skipped={skipped}")
    return n
```

### `upsert_actions()`

```python
def upsert_actions(sync_id: str, actions_list: list) -> int:
    """
    Batch upsert action dicts into actions table.
    Uses ON CONFLICT (action_key) DO UPDATE.
    action_key convention: '<source>:<item_id>:<action_type>'
    Returns: count upserted.
    Logs: supabase_actions_upserted
    """
    from datetime import datetime, timezone, timedelta

    if not actions_list:
        return 0

    gmt7     = timezone(timedelta(hours=7))
    run_date = datetime.now(gmt7).strftime("%Y-%m-%d")

    def esc(v):
        if v is None: return "NULL"
        return "'" + str(v).replace("'", "''") + "'"

    def esc_bool(v): return "true" if v else "false"
    def esc_num(v):  return str(v) if v is not None else "NULL"

    rows_sql = []
    for a in actions_list:
        if not a.get("action_key"):
            print(f"[upsert_actions] WARNING: skipping action with no action_key: {a.get('title','?')}")
            continue
        rows_sql.append(f"""(
            '{sync_id}'::uuid, '{run_date}',
            {esc(a.get('action_key'))},
            {esc(a.get('title', 'Untitled action'))},
            {esc(a.get('owner'))},
            {esc(a.get('due_date'))},
            {esc(a.get('source'))},
            {esc(a.get('source_ref'))},
            {esc(a.get('source_url'))},
            {esc(a.get('module'))},
            {esc(a.get('market'))},
            {esc(a.get('priority', 'P2'))},
            {esc(a.get('status', 'open'))},
            {esc(a.get('timebox'))},
            {esc_bool(a.get('is_client_facing', False))},
            {esc(a.get('draft_reply'))},
            {esc_num(a.get('confidence'))}
        )""")

    if not rows_sql:
        return 0

    values = ",\n".join(rows_sql)
    query = f"""
    INSERT INTO actions (
        sync_id, run_date, action_key, title, owner, due_date, source,
        source_ref, source_url, module, market, priority, status, timebox,
        is_client_facing, draft_reply, confidence
    ) VALUES {values}
    ON CONFLICT (action_key) DO UPDATE SET
        sync_id          = EXCLUDED.sync_id,
        run_date         = EXCLUDED.run_date,
        title            = EXCLUDED.title,
        owner            = EXCLUDED.owner,
        due_date         = EXCLUDED.due_date,
        source           = EXCLUDED.source,
        source_ref       = EXCLUDED.source_ref,
        source_url       = EXCLUDED.source_url,
        module           = EXCLUDED.module,
        market           = EXCLUDED.market,
        priority         = EXCLUDED.priority,
        status           = EXCLUDED.status,
        timebox          = EXCLUDED.timebox,
        is_client_facing = EXCLUDED.is_client_facing,
        draft_reply      = COALESCE(EXCLUDED.draft_reply, actions.draft_reply),
        confidence       = EXCLUDED.confidence,
        updated_at       = now();
    """
    supabase_sql(query)
    print(f"[upsert_actions] supabase_actions_upserted: count={len(rows_sql)}")
    return len(rows_sql)
```

### `upsert_decisions()`

```python
def upsert_decisions(sync_id: str, decisions_list: list) -> int:
    """
    Batch upsert decision dicts into decisions table.
    Uses ON CONFLICT (decision_key) DO UPDATE.
    status MUST be one of: confirmed | proposed | pending | unclear | rejected
    Returns: count upserted. Skips missing decision_key with WARNING.
    Logs: supabase_decisions_upserted

    Required DDL if DB constraint does not yet include 'rejected':
      ALTER TABLE public.decisions
      DROP CONSTRAINT IF EXISTS decisions_status_check;
      ALTER TABLE public.decisions
      ADD CONSTRAINT decisions_status_check
        CHECK (status IN ('confirmed','proposed','pending','unclear','rejected'));
    """
    from datetime import datetime, timezone, timedelta

    VALID_STATUS = {'confirmed', 'proposed', 'pending', 'unclear', 'rejected'}  # Fix 5

    if not decisions_list:
        return 0

    gmt7     = timezone(timedelta(hours=7))
    run_date = datetime.now(gmt7).strftime("%Y-%m-%d")

    def esc(v):
        if v is None: return "NULL"
        return "'" + str(v).replace("'", "''") + "'"

    rows_sql = []
    for d in decisions_list:
        if not d.get("decision_key"):
            print(f"[upsert_decisions] WARNING: skipping decision with no decision_key")
            continue
        status = d.get("status", "confirmed")
        if status not in VALID_STATUS:
            print(f"[upsert_decisions] WARNING: invalid status '{status}' → defaulting to 'unclear'")
            status = "unclear"
        rows_sql.append(f"""(
            '{run_date}',
            {esc(d.get('decision_key'))},
            {esc(d.get('decision_date', run_date))},
            {esc(d.get('description', ''))},
            {esc(d.get('topic'))},
            {esc(d.get('module'))},
            {esc(d.get('market'))},
            {esc(d.get('source'))},
            {esc(d.get('source_ref'))},
            {esc(d.get('source_url'))},
            {esc(d.get('made_by'))},
            {esc(status)}
        )""")

    if not rows_sql:
        return 0

    values = ",\n".join(rows_sql)
    query = f"""
    INSERT INTO decisions (
        run_date, decision_key, decision_date, description, topic, module,
        market, source, source_ref, source_url, made_by, status
    ) VALUES {values}
    ON CONFLICT (decision_key) DO UPDATE SET
        run_date      = EXCLUDED.run_date,
        decision_date = EXCLUDED.decision_date,
        description   = EXCLUDED.description,
        topic         = EXCLUDED.topic,
        module        = EXCLUDED.module,
        market        = EXCLUDED.market,
        source        = EXCLUDED.source,
        source_ref    = EXCLUDED.source_ref,
        source_url    = EXCLUDED.source_url,
        made_by       = EXCLUDED.made_by,
        status        = EXCLUDED.status;
    """
    supabase_sql(query)
    print(f"[upsert_decisions] supabase_decisions_upserted: count={len(rows_sql)}")
    return len(rows_sql)
```

### `upsert_risks()`

```python
def upsert_risks(sync_id: str, risks_list: list) -> int:
    """
    Batch upsert risk dicts into risks table.
    Uses ON CONFLICT (risk_key) DO UPDATE.
    risk_key convention: '<module>-<market>-<slug>'
    Automatically updates last_seen = today on every upsert.
    Returns: count upserted.
    Logs: supabase_risks_upserted
    """
    from datetime import datetime, timezone, timedelta

    if not risks_list:
        return 0

    gmt7     = timezone(timedelta(hours=7))
    run_date = datetime.now(gmt7).strftime("%Y-%m-%d")

    def esc(v):
        if v is None: return "NULL"
        return "'" + str(v).replace("'", "''") + "'"

    rows_sql = []
    for r in risks_list:
        if not r.get("risk_key"):
            print(f"[upsert_risks] WARNING: skipping risk with no risk_key")
            continue
        rows_sql.append(f"""(
            '{run_date}',
            {esc(r.get('risk_key'))},
            {esc(r.get('title', 'Untitled risk'))},
            {esc(r.get('description'))},
            {esc(r.get('module'))},
            {esc(r.get('market'))},
            {esc(r.get('severity', 'medium'))},
            {esc(r.get('status', 'open'))},
            {esc(r.get('mitigation'))},
            {esc(r.get('owner'))},
            {esc(r.get('source_url'))}
        )""")

    if not rows_sql:
        return 0

    values = ",\n".join(rows_sql)
    query = f"""
    INSERT INTO risks (
        run_date, risk_key, title, description, module, market,
        severity, status, mitigation, owner, source_url
    ) VALUES {values}
    ON CONFLICT (risk_key) DO UPDATE SET
        run_date    = EXCLUDED.run_date,
        title       = EXCLUDED.title,
        description = COALESCE(EXCLUDED.description, risks.description),
        module      = EXCLUDED.module,
        market      = EXCLUDED.market,
        severity    = EXCLUDED.severity,
        status      = EXCLUDED.status,
        mitigation  = COALESCE(EXCLUDED.mitigation, risks.mitigation),
        owner       = EXCLUDED.owner,
        source_url  = COALESCE(EXCLUDED.source_url, risks.source_url),
        last_seen   = CURRENT_DATE,
        updated_at  = now();
    """
    supabase_sql(query)
    print(f"[upsert_risks] supabase_risks_upserted: count={len(rows_sql)}")
    return len(rows_sql)
```

### `capture_outcome_signals()` — Loop v2 (outcome-aware learning)

```python
def capture_outcome_signals(since_ts: str = None) -> dict:
    """
    LOOP v2 — emit `outcome_signal` knowledge_facts for actions/risks that reached a
    TERMINAL state since `since_ts`, scoring the operator's earlier PREDICTION against
    what actually happened. Idempotent (fact_key 'out:<kind>:<ref>'; skips refs already
    captured) so it is safe to call on every sync. NO new table/column — fact_type is
    free-text; correctness comes from the NOT EXISTS guard, since_ts only bounds the scan.

    Called by: omni-data-sync STEP 7 (since_ts = last sync run_at); read back by
    omni-operator-learning (calibration denominators) and omni-self-improve.

    Returns: {"actions": n, "risks": n,
              "verdicts": {hit,over,under,neutral}, "since": since_ts}

    Verdict taxonomy (the learning value — was the prediction right?):
      ACTION  P0/P1 → done        = hit     (correctly prioritized AND actioned)
      ACTION  P0/P1 → superseded  = over    (cried wolf — ranked high, never needed)
      ACTION  P2    → blocked     = under   (under-ranked — low item became a blocker)
      ACTION  other terminal      = neutral (denominator only)
      RISK    materialized=True   = hit     (flagged risk that actually occurred)
      RISK    materialized=False  = neutral (mitigated/avoided — a good outcome, not a miss)
    NOTE: a risk that occurred but was NEVER flagged leaves no risks row, so RECALL gaps
    are invisible here — handled later by escalation cross-ref (out of scope v2.0).
    """
    from datetime import datetime, timezone, timedelta
    gmt7 = timezone(timedelta(hours=7))
    now  = datetime.now(gmt7)
    since = since_ts or "epoch"            # 'epoch' → first run captures the existing backlog once
    exp   = (now + timedelta(days=120)).isoformat()   # LEARNING_OUTCOME_EXPIRY_DAYS (move to omni-config §10B)
    REALIZED_KW = ("realiz", "occur", "materializ", "triggered", "hit")

    def esc(v): return "NULL" if v is None else "'" + str(v).replace("'", "''") + "'"
    since_sql = "to_timestamp(0)" if since in (None, "epoch") else esc(since) + "::timestamptz"

    out = {"actions": 0, "risks": 0,
           "verdicts": {"hit": 0, "over": 0, "under": 0, "neutral": 0}, "since": since}

    # ---- ACTIONS: terminal since since_ts, not yet captured ----
    for r in (supabase_sql(f"""
        SELECT a.action_key, a.title, a.owner, a.priority, a.status,
               a.created_at, a.updated_at
        FROM actions a
        WHERE a.status IN ('done','blocked','superseded')
          AND a.updated_at > {since_sql}
          AND NOT EXISTS (SELECT 1 FROM knowledge_facts k
                          WHERE k.fact_type='outcome_signal'
                            AND k.fact_key = 'out:action:' || a.action_key)
        ORDER BY a.updated_at;
    """) or []):
        pr, st = (r.get("priority") or "P2"), (r.get("status") or "")
        if   pr in ("P0", "P1") and st == "done":        v = "hit"
        elif pr in ("P0", "P1") and st == "superseded":  v = "over"
        elif pr == "P2"        and st == "blocked":      v = "under"
        else:                                            v = "neutral"
        days = None
        try:
            c, u = r.get("created_at"), r.get("updated_at")
            if c and u:
                days = (datetime.fromisoformat(str(u)) - datetime.fromisoformat(str(c))).days
        except Exception:
            pass
        upsert_knowledge_fact("outcome_signal", f"out:action:{r['action_key']}", {
            "kind": "action", "ref": r["action_key"], "title": r.get("title"),
            "predicted_priority": pr, "owner": r.get("owner"),
            "final_status": st, "days_open": days, "materialized": None,
            "verdict": v, "category": "ranking", "captured_at": now.isoformat(),
        }, scope="global", source_skill="omni-utils:loop-v2", expires_at=exp)
        out["actions"] += 1; out["verdicts"][v] += 1

    # ---- RISKS: non-open & changed since since_ts, not yet captured ----
    for r in (supabase_sql(f"""
        SELECT r.risk_key, r.title, r.module, r.market, r.severity, r.status,
               r.owner, r.created_at, r.updated_at
        FROM risks r
        WHERE lower(coalesce(r.status,'')) NOT IN ('open','active','monitoring','')
          AND r.updated_at > {since_sql}
          AND NOT EXISTS (SELECT 1 FROM knowledge_facts k
                          WHERE k.fact_type='outcome_signal'
                            AND k.fact_key = 'out:risk:' || r.risk_key)
        ORDER BY r.updated_at;
    """) or []):
        s = (r.get("status") or "").lower()
        materialized = any(kw in s for kw in REALIZED_KW) and "mitigat" not in s and "avoided" not in s
        v = "hit" if materialized else "neutral"
        upsert_knowledge_fact("outcome_signal", f"out:risk:{r['risk_key']}", {
            "kind": "risk", "ref": r["risk_key"], "title": r.get("title"),
            "predicted_priority": r.get("severity"), "owner": r.get("owner"),
            "module": r.get("module"), "market": r.get("market"),
            "final_status": r.get("status"), "days_open": None,
            "materialized": materialized, "verdict": v, "category": "risk",
            "captured_at": now.isoformat(),
        }, scope=(r.get("module") or "global"),
           source_skill="omni-utils:loop-v2", expires_at=exp)
        out["risks"] += 1; out["verdicts"][v] += 1

    print(f"[capture_outcome_signals] actions={out['actions']} risks={out['risks']} "
          f"verdicts={out['verdicts']} since={since}")
    return out
```

### `upsert_context_pack()`

```python
def upsert_context_pack(
    pack_type: str,
    run_date: str,
    sync_id: str,
    payload: dict,
    cache_age_h: float = 0.0,
    expires_at: str = None,
    is_stale: bool = False,
) -> bool:
    """
    Upsert a context pack into context_packs.
    Uses ON CONFLICT (pack_type, run_date) DO UPDATE.
    pack_type: one of briefing | eod | email_draft | full
    Returns True on success.
    Logs: supabase_context_pack_upserted
    """
    import json

    def esc(v):
        if v is None: return "NULL"
        return "'" + str(v).replace("'", "''") + "'"

    payload_sql = "'" + json.dumps(payload).replace("'", "''") + "'::jsonb"
    exp_sql     = esc(expires_at) if expires_at else "NULL"

    query = f"""
    INSERT INTO context_packs (pack_type, run_date, sync_id, payload, cache_age_h, expires_at, is_stale)
    VALUES (
        '{pack_type}', '{run_date}', '{sync_id}'::uuid,
        {payload_sql}, {cache_age_h}, {exp_sql}, {str(is_stale).lower()}
    )
    ON CONFLICT (pack_type, run_date) DO UPDATE SET
        sync_id     = EXCLUDED.sync_id,
        payload     = EXCLUDED.payload,
        cache_age_h = EXCLUDED.cache_age_h,
        expires_at  = EXCLUDED.expires_at,
        is_stale    = EXCLUDED.is_stale,
        generated_at = now();
    """
    supabase_sql(query)
    print(f"[upsert_context_pack] supabase_context_pack_upserted: type={pack_type} date={run_date}")
    return True


def get_latest_context_pack(pack_type: str) -> dict | None:
    """
    Returns the most recent context_pack row for the given pack_type.
    Returns full row dict including payload (parsed JSONB).
    """
    query = f"""
    SELECT id::text, pack_type, run_date::text, generated_at::text,
           expires_at::text, cache_age_h, is_stale, payload
    FROM context_packs
    WHERE pack_type = '{pack_type}'
    ORDER BY generated_at DESC
    LIMIT 1;
    """
    rows = supabase_sql(query)
    return rows[0] if rows else None
```

---

## UTILITY 7 — `cache_check()`

**v11.0: Supabase ONLY. No Mem0 fallback. If Supabase is unavailable → degraded=true + fallback SQL.**

```python
def cache_check(stale_threshold_h: int = None) -> dict:
    """
    v11.0: Reads sync_runs from Supabase ONLY.
    Mem0 is retired — there is NO Mem0 fallback.

    If Supabase is unavailable:
      - Returns mode="LIVE", degraded=True
      - Prints: "Mem0 skipped — Supabase is now the source of truth."
      - Does NOT attempt any Mem0 read

    Returns same dict shape as v10.x for backward compat:
    {
        "mode":      "CACHE" | "WARN" | "LIVE",
        "age_hours": float,
        "summary":   str,
        "last_run":  ISO timestamp str | None,
        "hit_type":  "supabase_sync_run" | "supabase_cache_check_missing" | "supabase_unavailable",
        "sync_id":   str | None,
        "degraded":  bool,
    }

    stale_threshold_h: defaults to 2h (CACHE_FRESH_H from omni-config).
    Skills with different thresholds (briefing=6h, eod=12h) pass explicitly.
    """
    from datetime import datetime, timezone, timedelta

    threshold = stale_threshold_h or 2

    try:
        return cache_check_from_supabase(max_age_hours=threshold)
    except Exception as e:
        print(f"[cache_check] supabase_unavailable: {e}")
        print("[cache_check] Mem0 skipped — Supabase is now the source of truth.")
        print("[cache_check] MANUAL ACTION: check Supabase connectivity, then re-run omni-data-sync.")
        return {
            "mode":      "LIVE",
            "age_hours": 999.0,
            "summary":   f"Supabase unavailable: {e}. Mem0 retired — no fallback available.",
            "last_run":  None,
            "hit_type":  "supabase_unavailable",
            "sync_id":   None,
            "degraded":  True,
        }


def cache_check_from_supabase(max_age_hours: float = 2.0) -> dict:
    """
    Primary cache freshness check using Supabase sync_runs table.
    Returns same shape as cache_check() for backward compat.
    Logs: supabase_cache_check_ok | supabase_cache_check_stale | supabase_cache_check_missing
    """
    from datetime import datetime, timezone, timedelta

    gmt7 = timezone(timedelta(hours=7))
    now  = datetime.now(gmt7)

    run = get_latest_sync_run()

    if not run:
        print("[cache_check_from_supabase] supabase_cache_check_missing: no sync_runs found")
        return {
            "mode":      "LIVE",
            "age_hours": 999.0,
            "summary":   "No sync run found in Supabase",
            "last_run":  None,
            "hit_type":  "supabase_cache_check_missing",
            "sync_id":   None,
            "degraded":  False,
        }

    try:
        run_at_str = run.get("run_at", "").replace("T", " ")[:16]
        last_run   = datetime.strptime(run_at_str[:16], "%Y-%m-%d %H:%M").replace(tzinfo=gmt7)
        age_hours  = (now - last_run).total_seconds() / 3600
    except Exception as e:
        print(f"[cache_check_from_supabase] timestamp parse error: {e}")
        age_hours = 999.0
        last_run  = None

    if age_hours < max_age_hours:
        mode      = "CACHE"
        log_token = "supabase_cache_check_ok"
    elif age_hours < 5.0:
        mode      = "WARN"
        log_token = "supabase_cache_check_stale"
    else:
        mode      = "LIVE"
        log_token = "supabase_cache_check_stale"

    summary = (f"Last sync {round(age_hours,1)}h ago "
               f"({run.get('run_at','?')[:16]}) "
               f"type={run.get('sync_type','?')} "
               f"status={run.get('status','?')}")

    print(f"[cache_check_from_supabase] {log_token}: age={round(age_hours,1)}h mode={mode}")

    return {
        "mode":      mode,
        "age_hours": round(age_hours, 1),
        "summary":   summary,
        "last_run":  last_run.isoformat() if last_run else None,
        "hit_type":  "supabase_sync_run",
        "sync_id":   run.get("id"),
        "degraded":  False,
    }
```

---

## UTILITY 8 — `get_context_pack()`

**v11.0: Supabase ONLY. No Mem0 fallback. If Supabase is unavailable → degraded=true.**

```python
def get_context_pack(pack_type: str, stale_threshold_h: int = 2) -> dict:
    """
    v11.0: Calls build_context_pack_from_supabase() ONLY.
    Mem0 is retired — there is NO _get_context_pack_legacy() fallback.

    If Supabase is unavailable:
      - Returns degraded=True, empty data fields
      - Prints: "Mem0 skipped — Supabase is now the source of truth."
      - Does NOT attempt any Mem0 read

    Return shape (preserved for backward compat):
    {
        "pack_type":      str,
        "loaded_at":      str,
        "cache_age_h":    float,
        "needs_sync":     bool,
        "missing":        [],
        "stale":          [],
        "sources_failed": [str],
        "cache_log":      {"supabase": str},
        "source":         "supabase",
        "degraded":       bool,
        "sync_id":        str | None,
        "freshness":      {...},
        "data": {
            "top_actions":            [row dicts],
            "top_risks":              [row dicts],
            "decisions":              [row dicts],
            "waiting_on_client":      [row dicts],
            "waiting_on_team":        [row dicts],
            "clickup_replies_needed": [row dicts],
            "meetings_to_prepare":    [row dicts],
            "suggested_drafts":       [row dicts],
            "briefing_notes":         [],
            # Legacy compat aliases:
            "emails":          [],  # deprecated — sourced from source_items now
            "teams":           [],  # deprecated — sourced from source_items now
            "urgent":          [top_actions],
            "calendar":        [meetings_to_prepare],
            "sync_meta":       "supabase:<timestamp>",
            "clickup":         {},
            "actions":         [action titles],
            "intel_pattern":   [],
            "intel_risk":      [top_risks],
            "intel_decision":  [decisions],
            "comment_signals": [clickup_replies_needed],
            "comment_signals_open": [clickup_replies_needed],
        }
    }
    """
    from datetime import datetime, timezone, timedelta

    gmt7 = timezone(timedelta(hours=7))
    now  = datetime.now(gmt7)

    try:
        sb_pack = build_context_pack_from_supabase()

        age_h      = sb_pack["freshness"]["cache_age_hours"]
        needs_sync = age_h >= stale_threshold_h

        return {
            "pack_type":      pack_type,
            "loaded_at":      now.strftime("%Y-%m-%d %H:%M GMT+7"),
            "cache_age_h":    age_h,
            "needs_sync":     needs_sync,
            "missing":        [],
            "stale":          ["supabase_data"] if age_h >= stale_threshold_h else [],
            "sources_failed": sb_pack["freshness"].get("warnings", []),
            "cache_log":      {"supabase": "context_pack_built_from_supabase"},
            "source":         "supabase",
            # Fix 4: propagate degraded flag from sb_pack — do not hardcode False
            # sb_pack["degraded"] is True when freshness warnings exist or data is partial
            "degraded":       sb_pack.get("degraded", False),
            "sync_id":        sb_pack.get("sync_id"),
            # Fix 4: preserve freshness.status=partial when sb_pack has warnings
            "freshness":      sb_pack["freshness"],
            "data": {
                "top_actions":                sb_pack["top_actions"],
                "top_risks":                  sb_pack["top_risks"],
                "open_risks":                 sb_pack["top_risks"],
                "decisions":                  sb_pack["decisions"],
                # Fix 6: use canonical renamed key; legacy alias also preserved
                "client_facing_open_actions": sb_pack.get("client_facing_open_actions", []),
                "waiting_on_client":          sb_pack.get("client_facing_open_actions", []),
                "waiting_on_team":            sb_pack["waiting_on_team"],
                "clickup_replies_needed":     sb_pack["clickup_replies_needed"],
                "meetings_to_prepare":        sb_pack["meetings_to_prepare"],
                "suggested_drafts":           sb_pack.get("suggested_drafts", []),
                "briefing_notes":             [],
                # Legacy compat aliases
                "emails":          [],
                "teams":           [],
                "urgent":          sb_pack["top_actions"],
                "calendar":        sb_pack["meetings_to_prepare"],
                "sync_meta":       f"supabase:{sb_pack['freshness'].get('latest_sync_at','?')}",
                "clickup":         {},
                "actions":         [a.get("title","") for a in sb_pack["top_actions"]],
                "intel_pattern":   [],
                "intel_risk":      sb_pack["top_risks"],
                "intel_decision":  sb_pack["decisions"],
                "comment_signals": sb_pack["clickup_replies_needed"],
                "comment_signals_open": sb_pack["clickup_replies_needed"],
            },
        }

    except Exception as e:
        print(f"[get_context_pack] supabase_unavailable: {e}")
        print("[get_context_pack] Mem0 skipped — Supabase is now the source of truth.")
        print("[get_context_pack] MANUAL ACTION: check Supabase connectivity.")

        # Return empty degraded pack — same shape so callers don't crash
        empty = []
        return {
            "pack_type":      pack_type,
            "loaded_at":      now.strftime("%Y-%m-%d %H:%M GMT+7"),
            "cache_age_h":    999.0,
            "needs_sync":     True,
            "missing":        ["supabase_unavailable"],
            "stale":          [],
            "sources_failed": [str(e)],
            "cache_log":      {"supabase": "unavailable"},
            "source":         "supabase",
            "degraded":       True,
            "sync_id":        None,
            "freshness":      {
                "status":          "missing",
                "cache_age_hours": 999.0,
                "latest_sync_at":  None,
                "warnings":        [f"Supabase unavailable: {e}"],
            },
            "data": {
                "top_actions": empty, "top_risks": empty, "open_risks": empty,
                "decisions": empty,
                "client_facing_open_actions": empty,
                "waiting_on_client": empty,
                "waiting_on_team": empty, "clickup_replies_needed": empty,
                "meetings_to_prepare": empty, "suggested_drafts": empty,
                "briefing_notes": empty, "emails": empty, "teams": empty,
                "urgent": empty, "calendar": empty, "sync_meta": None,
                "clickup": {}, "actions": empty, "intel_pattern": empty,
                "intel_risk": empty, "intel_decision": empty,
                "comment_signals": empty, "comment_signals_open": empty,
            },
        }
```

---

## UTILITY 9 — `build_context_pack_from_supabase()`

```python
def build_context_pack_from_supabase(run_date: str = None) -> dict:
    """
    Build a structured context pack from Supabase for the briefing/EOD skills.
    v11.0: All fields guaranteed arrays — never null.
    v11.0: Also enriches with knowledge_facts for intel fields.

    Returns:
    {
        "source":   "supabase",
        "degraded": False,
        "run_date": "YYYY-MM-DD",
        "sync_id":  str | None,
        "freshness": {
            "status":          "fresh" | "stale" | "missing" | "partial",
            "cache_age_hours": float,
            "latest_sync_at":  ISO str | None,
            "warnings":        [str],
        },
        "top_actions":            [row dicts],
        "top_risks":              [row dicts],
        "open_risks":             [row dicts],
        "decisions":              [row dicts],
        "waiting_on_client":      [row dicts],
        "waiting_on_team":        [row dicts],
        "clickup_replies_needed": [row dicts],
        "meetings_to_prepare":    [row dicts],
        "suggested_drafts":       [row dicts],
        "briefing_notes":         [],
        "intel_daily":            [knowledge_fact rows],
        "intel_patterns":         [knowledge_fact rows],
        "feature_rollup":         [feature_status rows]   # v11.1
    }
    Logs: context_pack_built_from_supabase
    """
    from datetime import datetime, timezone, timedelta

    gmt7     = timezone(timedelta(hours=7))
    today    = run_date or datetime.now(gmt7).strftime("%Y-%m-%d")
    warnings = []
    degraded = False

    # ── Freshness check ──────────────────────────────────────────────────────
    latest_run = get_latest_sync_run()
    if not latest_run:
        warnings.append("No sync_run found in Supabase — data may be empty")
        freshness_status = "missing"
        cache_age_h      = 999.0
        sync_id          = None
        latest_sync_at   = None
    else:
        sync_id        = latest_run.get("id")
        latest_sync_at = latest_run.get("run_at")
        try:
            run_at_str  = latest_sync_at.replace("T", " ")[:16]
            last_run_dt = datetime.strptime(run_at_str, "%Y-%m-%d %H:%M").replace(tzinfo=gmt7)
            cache_age_h = (datetime.now(gmt7) - last_run_dt).total_seconds() / 3600
        except:
            cache_age_h = 999.0

        if cache_age_h < 2:
            freshness_status = "fresh"
        elif cache_age_h < 6:
            freshness_status = "stale"
            warnings.append(f"Cache is {round(cache_age_h,1)}h old — consider re-syncing")
        else:
            freshness_status = "stale"
            warnings.append(f"Cache is {round(cache_age_h,1)}h old — re-sync recommended")

    # ── Query helper ─────────────────────────────────────────────────────────
    def safe_query(query: str, label: str) -> list:
        try:
            rows = supabase_sql(query)
            return rows if rows else []
        except Exception as e:
            warnings.append(f"{label}: query failed — {e}")
            return []

    # ── top_actions ──────────────────────────────────────────────────────────
    top_actions = safe_query("""
        SELECT id::text, action_key, title, owner, due_date::text, source,
               source_ref, source_url, module, market, priority, status,
               timebox, is_client_facing, draft_reply, confidence, updated_at::text
        FROM actions
        WHERE status IN ('open', 'in_progress', 'blocked')
        ORDER BY
            CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 WHEN 'P3' THEN 3 ELSE 4 END ASC,
            due_date ASC NULLS LAST,
            updated_at DESC
        LIMIT 30;
    """, "top_actions")

    # ── top_risks ────────────────────────────────────────────────────────────
    top_risks = safe_query("""
        SELECT id::text, risk_key, title, description, module, market,
               severity, status, mitigation, owner, source_url,
               first_seen::text, last_seen::text
        FROM risks
        WHERE status IN ('open', 'monitoring')
        ORDER BY
            CASE severity WHEN 'P1' THEN 1 WHEN 'high' THEN 2 WHEN 'P2' THEN 3
                          WHEN 'medium' THEN 4 WHEN 'P3' THEN 5 WHEN 'low' THEN 6 ELSE 7 END ASC,
            last_seen DESC
        LIMIT 20;
    """, "top_risks")

    # ── decisions ────────────────────────────────────────────────────────────
    decisions = safe_query(f"""
        SELECT id::text, decision_key, decision_date::text, description, topic,
               module, market, source, source_url, made_by, status
        FROM decisions
        WHERE status IN ('confirmed', 'pending', 'proposed')
          AND superseded_by IS NULL
          AND run_date >= '{today}'::date - INTERVAL '7 days'
        ORDER BY decision_date DESC
        LIMIT 20;
    """, "decisions")

    # ── client_facing_open_actions ───────────────────────────────────────────
    # Fix 6: Renamed from 'waiting_on_client'.
    # Rationale: owner NOT IN ('Nghiem') AND is_client_facing=true does NOT
    # mean the client must respond — it means the action involves a client-facing
    # activity owned by someone other than Nghiem. Labelling this "waiting on client"
    # was misleading. Renamed to client_facing_open_actions for accuracy.
    #
    # To add true "waiting on" semantics in future, run this DDL:
    #   ALTER TABLE public.actions
    #   ADD COLUMN IF NOT EXISTS waiting_for      text,
    #   ADD COLUMN IF NOT EXISTS waiting_for_type text;
    # Then filter on: waiting_for IS NOT NULL AND waiting_for_type = 'client'
    client_facing_open_actions_raw = safe_query("""
        SELECT id::text, action_key, title, owner, due_date::text,
               module, market, priority, status, source_url,
               is_client_facing, draft_reply
        FROM actions
        WHERE owner NOT IN ('Nghiem')
          AND is_client_facing = true
          AND status NOT IN ('done', 'cancelled')
        ORDER BY
            CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END ASC,
            due_date ASC NULLS LAST
        LIMIT 15;
    """, "client_facing_open_actions")

    client_facing_open_actions = []
    for row in client_facing_open_actions_raw:
        row["owner_label"] = f"Owned by {row.get('owner','?')}"
        client_facing_open_actions.append(row)

    # ── waiting_on_team ──────────────────────────────────────────────────────
    waiting_on_team = safe_query("""
        SELECT id::text, action_key, title, owner, due_date::text,
               module, market, priority, status, source_url
        FROM actions
        WHERE owner IS NOT NULL
          AND owner NOT IN ('Nghiem', 'client')
          AND status NOT IN ('done', 'cancelled')
        ORDER BY
            CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END ASC,
            due_date ASC NULLS LAST
        LIMIT 15;
    """, "waiting_on_team")

    # ── clickup_replies_needed ───────────────────────────────────────────────
    clickup_replies_raw = safe_query("""
        SELECT id::text, item_id, title, summary, body_excerpt,
               source_url, market, module, priority, assignee,
               raw_json->>'response_needed'    AS response_needed,
               raw_json->>'reply_class'         AS reply_class,
               raw_json->>'human_review'        AS human_review,
               raw_json->>'suggested_reply'     AS suggested_reply,
               raw_json->>'human_review_reason' AS human_review_reason,
               synced_at::text
        FROM source_items
        WHERE source_type = 'clickup_comment'
          AND (is_urgent = true OR priority IN ('P1', 'urgent')
               OR 'reply_needed' = ANY(tags))
        ORDER BY
            CASE priority WHEN 'urgent' THEN 0 WHEN 'P1' THEN 1 ELSE 2 END,
            synced_at DESC
        LIMIT 15;
    """, "clickup_replies_needed")

    clickup_action_replies = safe_query("""
        SELECT action_key, title, owner, due_date::text, module, market,
               priority, draft_reply, confidence, is_client_facing, source_url
        FROM actions
        WHERE source = 'clickup_comment'
          AND (draft_reply IS NOT NULL OR action_key LIKE '%reply%')
          AND status != 'done'
        ORDER BY
            CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END ASC
        LIMIT 10;
    """, "clickup_action_replies")

    clickup_replies_needed = list(clickup_replies_raw)
    raw_ids = {r.get("item_id", "") for r in clickup_replies_raw}
    for a in clickup_action_replies:
        key = a.get("action_key", "")
        if not any(rid in key for rid in raw_ids if rid):
            clickup_replies_needed.append({
                "item_id": key, "title": a.get("title"),
                "source_url": a.get("source_url"), "market": a.get("market"),
                "module": a.get("module"), "priority": a.get("priority"),
                "response_needed": "true", "suggested_reply": a.get("draft_reply"),
                "human_review": "true", "confidence": a.get("confidence"),
                "owner": a.get("owner"),
            })

    # ── meetings_to_prepare ──────────────────────────────────────────────────
    meetings_from_source = safe_query("""
        SELECT item_id, title, summary, due_date::text,
               market, module, source_url, tags, 'source_item' AS _origin
        FROM source_items
        WHERE source_type = 'calendar_event'
          AND 'PREP_NEEDED' = ANY(tags)
        ORDER BY
            CASE WHEN title ILIKE '%TODAY%' THEN 0 ELSE 1 END, item_id
        LIMIT 10;
    """, "meetings_from_source")

    meetings_from_actions = safe_query("""
        SELECT action_key AS item_id, title, NULL AS summary, due_date::text,
               market, module, source_url, NULL AS tags, 'action' AS _origin,
               timebox AS prep_notes
        FROM actions
        WHERE source = 'calendar_event'
          AND action_key LIKE 'calendar_event:%'
          AND status NOT IN ('done', 'cancelled')
        ORDER BY
            CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END,
            due_date ASC NULLS LAST
        LIMIT 10;
    """, "meetings_from_actions")

    if meetings_from_source:
        meetings_to_prepare = []
        for m in meetings_from_source:
            summary = m.get("summary", "") or ""
            prep_note = ""
            if "PREP NEEDED:" in summary:
                prep_note = summary.split("PREP NEEDED:")[-1].strip().split(".")[0]
            elif "PREP_NEEDED" in (m.get("tags") or []):
                prep_note = "Prepare materials for this meeting"
            m["prep_notes"]      = prep_note
            m["related_market"]  = m.pop("market", None)
            m["related_module"]  = m.pop("module", None)
            m["owner"]           = "Nghiem"
            m["priority"]        = "P1"
            meetings_to_prepare.append(m)
    else:
        meetings_to_prepare = []
        for m in meetings_from_actions:
            m["related_market"] = m.pop("market", None)
            m["related_module"] = m.pop("module", None)
            m["owner"]          = "Nghiem"
            meetings_to_prepare.append(m)

    # ── suggested_drafts ─────────────────────────────────────────────────────
    draft_actions = safe_query("""
        SELECT action_key, title, owner, due_date::text, module, market,
               priority, draft_reply, confidence, is_client_facing, source, source_url
        FROM actions
        WHERE draft_reply IS NOT NULL
          AND status NOT IN ('done', 'cancelled')
        ORDER BY
            CASE priority WHEN 'P1' THEN 1 WHEN 'P2' THEN 2 ELSE 3 END ASC
        LIMIT 10;
    """, "suggested_drafts")

    suggested_drafts = []
    for a in draft_actions:
        suggested_drafts.append({
            "action_key":       a.get("action_key"),
            "title":            a.get("title"),
            "owner":            a.get("owner"),
            "draft_reply":      a.get("draft_reply"),
            "confidence":       a.get("confidence"),
            "human_review":     True,
            "module":           a.get("module"),
            "market":           a.get("market"),
            "source":           a.get("source"),
            "source_url":       a.get("source_url"),
            "is_client_facing": a.get("is_client_facing"),
        })
    for r in clickup_replies_needed:
        sr = r.get("suggested_reply")
        if sr and not any(d.get("action_key") == r.get("item_id") for d in suggested_drafts):
            suggested_drafts.append({
                "action_key":  r.get("item_id"), "title": r.get("title"),
                "owner":       r.get("owner") or r.get("assignee"),
                "draft_reply": sr, "confidence": r.get("confidence"),
                "human_review": True, "module": r.get("module"),
                "market":      r.get("market"), "source": "clickup_comment",
            })

    # ── knowledge_facts enrichment (intel_daily, intel_patterns) ─────────────
    intel_daily   = get_knowledge_facts("intel_daily",   limit=7)
    intel_patterns = get_knowledge_facts("intel_pattern", limit=20)

    # ── feature_rollup (v11.1) — per-OPCO feature status board ──────────────
    try:
        feature_rollup = get_feature_rollup(only_active=True)
    except Exception as e:
        warnings.append(f"feature_rollup: query failed — {e}")
        feature_rollup = []

    if warnings:
        freshness_status = "partial" if freshness_status == "fresh" else freshness_status

    print(f"[build_context_pack_from_supabase] context_pack_built_from_supabase: "
          f"date={today} actions={len(top_actions)} risks={len(top_risks)} "
          f"decisions={len(decisions)} meetings={len(meetings_to_prepare)} "
          f"client_facing={len(client_facing_open_actions)} waiting_team={len(waiting_on_team)} "
          f"replies={len(clickup_replies_needed)} drafts={len(suggested_drafts)} "
          f"intel_daily={len(intel_daily)} patterns={len(intel_patterns)} "
          f"features={len(feature_rollup)} warnings={len(warnings)}")

    return {
        "source":                      "supabase",
        "degraded":                    degraded,
        "run_date":                    today,
        "sync_id":                     sync_id,
        "freshness": {
            "status":          freshness_status,
            "cache_age_hours": round(cache_age_h, 1),
            "latest_sync_at":  latest_sync_at,
            "warnings":        warnings,
        },
        "top_actions":                 top_actions,
        "top_risks":                   top_risks,
        "open_risks":                  top_risks,
        "decisions":                   decisions,
        # Fix 6: renamed from 'waiting_on_client' — see comment above for rationale
        "client_facing_open_actions":  client_facing_open_actions,
        # Legacy alias preserved for backward compat — points to same list
        "waiting_on_client":           client_facing_open_actions,
        "waiting_on_team":             waiting_on_team,
        "clickup_replies_needed":      clickup_replies_needed,
        "meetings_to_prepare":         meetings_to_prepare,
        "suggested_drafts":            suggested_drafts,
        "briefing_notes":              [],
        "intel_daily":                 intel_daily,
        "intel_patterns":              intel_patterns,
        "feature_rollup":              feature_rollup,
    }
```

---

## UTILITY 10 — Maintenance and Audit Helpers

### `cleanup_old_raw_items()`

```python
def cleanup_old_raw_items(retention_days: int = 7) -> dict:
    """
    Delete source_items older than retention_days (per source_type window).
    Runs after every FULL sync (STEP 8 of omni-data-sync).

    Windows:
      email, sent_email, teams_message, calendar_event → retention_days (default 7)
      clickup_task, clickup_comment                    → retention_days * 2 (default 14)
      ado_work_item                                    → retention_days * 4 (default 28)

    Returns: {"deleted_total": int, "by_type": {source_type: count}}
    """
    windows = {
        "email":           retention_days,
        "sent_email":      retention_days,
        "teams_message":   retention_days,
        "clickup_task":    retention_days * 2,
        "clickup_comment": retention_days * 2,
        "ado_work_item":   retention_days * 4,
        "calendar_event":  retention_days,
    }

    deleted_total = 0
    by_type = {}

    for source_type, days in windows.items():
        result = supabase_sql(f"""
            WITH deleted AS (
                DELETE FROM source_items
                WHERE source_type = '{source_type}'
                  AND synced_at < now() - INTERVAL '{days} days'
                RETURNING id
            )
            SELECT count(*) AS n FROM deleted;
        """)
        n = int(result[0]["n"]) if result and result[0].get("n") else 0
        by_type[source_type] = n
        deleted_total += n
        if n > 0:
            print(f"[cleanup_old_raw_items] deleted {n} {source_type} items older than {days}d")

    print(f"[cleanup_old_raw_items] total deleted={deleted_total}")
    return {"deleted_total": deleted_total, "by_type": by_type}
```

### `cleanup_stale_knowledge_facts()`

```python
def cleanup_stale_knowledge_facts() -> dict:
    """
    Delete knowledge_facts rows where expires_at < NOW().
    Called after every FULL sync run.
    Returns: {"deleted": int}
    """
    result = supabase_sql("""
        WITH deleted AS (
            DELETE FROM knowledge_facts
            WHERE expires_at IS NOT NULL AND expires_at < NOW()
            RETURNING id
        )
        SELECT count(*) AS n FROM deleted;
    """)
    n = int(result[0]["n"]) if result and result[0].get("n") else 0
    if n > 0:
        print(f"[cleanup_stale_knowledge_facts] deleted {n} expired knowledge_facts rows")
    return {"deleted": n}
```

### `run_duplicate_audit()`

```python
def run_duplicate_audit() -> dict:
    """
    Post-sync audit: query v_duplicate_audit view and report duplicate counts.
    Call at the end of every sync run (STEP 8).
    Returns dict: {"total_duplicates": int, "clean": bool, "by_table": {...}, "details": [...]}
    Logs: duplicate_audit_clean | duplicate_audit_violations
    """
    query = "SELECT * FROM v_duplicate_audit ORDER BY table_name;"
    rows  = supabase_sql(query) or []

    by_table = {
        "source_items":  0,
        "actions":       0,
        "risks":         0,
        "decisions":     0,
        "context_packs": 0,
        "knowledge_facts": 0,
    }
    for row in rows:
        tbl = row.get("table_name", "")
        cnt = int(row.get("row_count", 0))
        if tbl in by_table:
            by_table[tbl] += cnt - 1

    total = sum(by_table.values())
    clean = total == 0

    if clean:
        print("[run_duplicate_audit] duplicate_audit_clean: 0 duplicates across all tables")
    else:
        print(f"[run_duplicate_audit] duplicate_audit_violations: total={total} by_table={by_table}")

    return {
        "total_duplicates": total,
        "clean":            clean,
        "by_table":         by_table,
        "details":          rows if not clean else [],
    }
```

---

## UTILITY 11 — `diplomatic_mode()`

Unchanged from v10.x. Returns dict only — never writes anywhere.

```python
def diplomatic_mode(situation: str, context: dict = None) -> dict:
    """
    Returns private diagnosis + recommended public framing for sensitive situations.
    situation: one of the DIPLOMATIC_TRIGGERS keys, or free-text description
    context: optional dict — keys: stakeholder, topic, risk_level, module, opco
    Never writes to Supabase or Mem0. Read-only utility.
    """
    if context is None:
        context = {}

    APPROACH_MAP = {
        "scope_creep":          "frame as priority alignment, not rejection",
        "governance_overhead":  "suggest lightweight checkpoint instead of new layer",
        "timeline_pressure":    "confirm scope first, then commit timeline",
        "capacity_constraint":  "align backlog priority before committing extra FTE",
        "client_pressure":      "acknowledge urgency, propose structured resolution",
        "stakeholder_conflict": "neutral language, align on shared outcome",
        "delivery_risk":        "surface risk early with proposed mitigation",
        "ownership_ambiguity":  "explicitly name owner and next step",
        "extra_process_request": "suggest using existing process instead of adding new layer",
        "political_sensitivity": "neutral, factual, practical next step only",
    }

    AVOID_PHRASES = [
        "scope creep", "governance failure", "your team's fault",
        "that's not our responsibility", "we told you so",
        "this is outside our SOW", "you never mentioned this", "this wasn't agreed",
    ]

    USE_PHRASES = [
        "From delivery perspective, ...",
        "To keep this lightweight, ...",
        "To avoid adding extra overhead, ...",
        "I suggest we use the existing checkpoint to track this topic.",
        "Let's align on the expected outcome first.",
        "Before we commit the timeline, I suggest we first confirm the scope.",
        "We can support this, but we need to align the priority against the current committed backlog.",
        "This will help the team stay focused on delivery while still keeping visibility.",
        "Let me check with the team and come back with a clear proposal.",
    ]

    matched_approach = APPROACH_MAP.get(situation, "neutral, practical language with clear next step and owner")
    stakeholder = context.get("stakeholder", "unknown")
    risk_level  = context.get("risk_level", "medium")

    return {
        "triggered":              True,
        "private_diagnosis":      f"[INTERNAL ONLY] Situation: {situation}. Stakeholder: {stakeholder}. Risk: {risk_level}.",
        "public_framing":         f"Use delivery-focused, practical framing. {matched_approach}.",
        "recommended_approach":   matched_approach,
        "avoid_phrases":          AVOID_PHRASES,
        "use_phrases":            USE_PHRASES,
    }
```

---

## UTILITY 12 — Feature Status Rollup (v11.1)

Implements the `(OPCO, Feature)` entity layer per omni-config v1.5 Section 17.
Read config constants (`FEATURE_REGISTRY_SEED`, `FEATURE_RESOLUTION`,
`FEATURE_AUTODISCOVERY`, `FEATURE_STATUS_PRECEDENCE`, `SIGNAL_TO_FEATURE_STATUS`,
`FEATURE_AUTOSUPERSEDE`) before calling any function here.

### `load_feature_registry_seed()` — one-time bootstrap (idempotent)

```python
def load_feature_registry_seed() -> int:
    """
    Bootstrap feature_status from omni-config FEATURE_REGISTRY_SEED.
    Idempotent: ON CONFLICT (feature_key) DO NOTHING — the table is
    authoritative after first load; seed never overwrites live rows.
    Returns number of rows inserted. Logs: feature_registry_seeded.
    """
    rows = []
    for fkey, f in FEATURE_REGISTRY_SEED.items():
        opco = fkey.split(":")[0]
        rows.append(f"""(
            {esc(fkey)}, {esc(opco)}, {esc(f['module'])}, {esc(f['label'])},
            {esc_arr([a.lower() for a in f['aliases']])}, 'seeded'
        )""")
    sql = f"""
    INSERT INTO feature_status (feature_key, opco, module, label, aliases, registry_state)
    VALUES {','.join(rows)}
    ON CONFLICT (feature_key) DO NOTHING;
    """
    try:
        supabase_sql(sql)
    except Exception as e:
        _supabase_fallback_sql(sql, "load_feature_registry_seed")
        return 0
    n = supabase_sql("SELECT count(*) AS n FROM feature_status;")[0]["n"]
    print(f"[load_feature_registry_seed] feature_registry_seeded: total_rows={n}")
    return n
```

### `resolve_feature_key()` — tag a NormalizedSignal

```python
def resolve_feature_key(signal: dict, registry: list = None) -> str | None:
    """
    Resolve signal → feature_key per FEATURE_RESOLUTION (omni-config §17).
    registry: cached rows from feature_status (pass once per sync run:
      SELECT feature_key, opco, aliases FROM feature_status
      WHERE registry_state IN ('seeded','confirmed','candidate');)

    Resolution:
      1. OPCO: signal['opco'] field → else OPCO code/country name in
         title/subject/summary → else ClickUp list/task market → else None.
         OPCO is MANDATORY — no OPCO = return None (never guess).
      2. Feature: case-insensitive alias scan of title+summary+body_excerpt,
         longest-alias-first, within resolved OPCO first, then ALL-opco rows.
      3. No match → return f"{opco}:unmapped" (counted; auto-discovery
         handled in rollup step — never status-rolled).
    Alias auto-learn: when a match succeeds on a partial/fuzzy phrase not yet
    in aliases[], append it:
      UPDATE feature_status SET aliases = array_append(aliases, <phrase>),
        updated_at = NOW() WHERE feature_key = <fkey>
        AND NOT (<phrase> = ANY(aliases));
    """
```

Implementation notes (LLM-executed, not literal code): Claude performs the alias
match semantically — exact alias hit is authoritative; clear semantic equivalence
(e.g. "perfect outlet new BE" ≈ "new backend perfect outlet") counts as a match
AND triggers alias auto-learn. Ambiguous text → `<opco>:unmapped`, never guess.

### `rollup_feature_status()` — cross-source reconciliation + auto-supersede

```python
def rollup_feature_status(feature_key: str, window_signals: list = None) -> dict:
    """
    Recompute one feature's status from ALL linked sources, then apply
    auto-supersede per FEATURE_AUTOSUPERSEDE. Called by omni-data-sync
    STEP 6 for every feature_key touched in the current window.

    1. GATHER — linked items across sources:
       SELECT source_type, external_id, title, summary, priority, status,
              is_urgent, synced_at, raw_json
       FROM source_items WHERE feature_key = '<fkey>'
       ORDER BY synced_at DESC LIMIT 50;
       Plus open actions / open risks WHERE feature_key = '<fkey>'.

    2. DETERMINE STATUS — candidate = signal with highest
       FEATURE_STATUS_PRECEDENCE tier among signals ≤24h newer than the
       current status_updated_at; ties → most recent wins. Map via
       SIGNAL_TO_FEATURE_STATUS (INFO never changes status — evidence only).
       INCIDENT/BLOCKER newer than a 'deployed' status DOES override it
       (deploy then prod incident = incident).

    3. CONFIDENCE GATE (FEATURE_AUTOSUPERSEDE.high_confidence_requires):
       HIGH  → write new status to feature_status; auto-supersede linked
               open actions whose intent is satisfied by the new status
               (e.g. 'deploy X' action when X just deployed):
               UPDATE actions SET status='done',
                 raw_json = coalesce(raw_json,'{}'::jsonb) ||
                   jsonb_build_object('superseded_by','<fkey>',
                     'superseded_reason','<signal summary>',
                     'superseded_at', now()::text)
               WHERE feature_key='<fkey>' AND status IN ('open','in_progress','blocked')
                 AND <intent satisfied — Claude judges per action title>;
               NEVER supersede: Nghiem-owned actions with draft_reply pending,
               GOVERNANCE_REVIEW register actions. Append superseded keys to
               feature_status.superseded_actions (audit).
       LOWER → status unchanged; append signal to conflicts[]; briefing
               surfaces as 'status_conflict' for Nghiem review.

    4. UPSERT feature_status row: status fields, evidence (≤10 newest refs),
       open_counts snapshot, signal_count, updated_at=NOW().
       Candidate promotion: if registry_state='candidate' AND
       signal_count ≥ FEATURE_AUTODISCOVERY.min_signals_for_candidate →
       keep 'candidate', surface in EOD for confirm/merge/reject.

    Returns {feature_key, status, changed: bool, superseded: [action_keys],
             conflicts_added: int}.
    Logs: feature_rollup: key=<fkey> status=<s> changed=<b> superseded=<n>
    """
```

### `get_feature_rollup()` — reader for context pack / briefing

```python
def get_feature_rollup(opco: str = None, only_active: bool = True) -> list:
    """
    SELECT feature_key, opco, module, label, status, status_signal,
           status_actor, status_summary, status_updated_at::text,
           registry_state, open_counts,
           jsonb_array_length(conflicts) AS conflict_count,
           signal_count
    FROM feature_status
    WHERE registry_state != 'rejected'
      AND (only_active → status != 'unknown' OR conflict_count > 0
           OR registry_state = 'candidate')
      AND (opco filter if given)
    ORDER BY
      CASE status WHEN 'incident' THEN 0 WHEN 'blocked' THEN 1
                  WHEN 'at_risk' THEN 2 WHEN 'deployed' THEN 3
                  WHEN 'decided' THEN 4 ELSE 5 END,
      status_updated_at DESC NULLS LAST;
    """
```

### Auto-discovery (registry grows day by day)

During STEP 6 rollup, signals resolved to `<opco>:unmapped` are grouped by
recurring noun-phrase (Claude judgment). Any phrase appearing in ≥2 signals for
the same OPCO within the window → INSERT a `registry_state='candidate'` row
(`feature_key='<opco>:<slug>'`, aliases=[phrase]). Candidates roll up evidence
but their auto-supersede is DISABLED until Nghiem confirms (EOD review lists
candidates: confirm → 'confirmed', merge → move aliases to existing row +
'rejected', reject → 'rejected').

---

## SECURITY NOTE — RLS

Supabase public tables currently have **RLS disabled**.

**Do NOT auto-enable RLS from this skill.** Enabling RLS without policies will break Claude/Supabase MCP access immediately — all reads and writes will return empty or permission-denied.

Recommended future remediation (do this manually, in a dev branch first):
1. Define a **service-role / admin access policy** for the OMNI operator workflow.
2. Define **read/write policies** for each table (`source_items`, `actions`, `decisions`, `risks`, `knowledge_facts`, `user_preferences`, `project_context`, etc.).
3. Test fully in a Supabase development branch before applying to production.
4. Enable RLS only after all policies are validated and the MCP connection is confirmed working under the new policies.

---

## GUARDRAILS — v11.0

- **Mem0 is FULLY RETIRED.** No reads, no writes, no fallbacks, no tag scanning. Any call to a Mem0 function returns `"SKIPPED — Mem0 retired. Use Supabase helper instead."` via the stub shims.
- **`supabase_sql()` raises on error** (Fix 2). It no longer returns `None`. Every write helper wraps `supabase_sql()` in a try/except and calls `_supabase_fallback_sql()` on failure. A silent `None` return was a false-success bug.
- **`write_action()` uses second-precision + summary hash key** (Fix 3). Format: `action:<skill>:<type>:<YYYY-MM-DDTHH:MM:SS>:<hash8>`. Prevents same-minute collision drops.
- **`actions.raw_json` column required** (Fix 1). Run `ALTER TABLE public.actions ADD COLUMN IF NOT EXISTS raw_json jsonb` before deploying v11.0.
- **`decisions.status` includes `rejected`** (Fix 5). Run constraint DDL patch if existing DB constraint does not allow `rejected`.
- **`client_facing_open_actions` replaces `waiting_on_client`** (Fix 6). Legacy key `waiting_on_client` preserved as alias pointing to the same list. Do not label actions as "waiting on client" unless source data explicitly indicates client/stakeholder must respond. Future schema: add `waiting_for` / `waiting_for_type` columns.
- **`get_context_pack()` propagates `degraded` from `sb_pack`** (Fix 4). Never hardcodes `degraded=False`. Freshness status `partial` is preserved when warnings exist.
- **All writes go through helpers.** Never call `Supabase.execute_sql()` with INSERT/UPDATE directly in skills. Always use the upsert helpers defined here.
- **Supabase unavailability → output SQL.** If any Supabase write fails, print exact SQL/JSON payload for manual insert via `_supabase_fallback_sql()`. Do NOT silently drop data.
- **`cache_check()` and `get_context_pack()` are Supabase-only.** No legacy Mem0 fallback. If Supabase fails → return `degraded=true` with empty data.
- **Dedup keys are mandatory.** `action_key`, `decision_key`, `risk_key`, `fact_key` must be supplied. Items without keys are skipped with WARNING log.
- **DDL via `Supabase.apply_migration()` only.** Never create tables or alter schema via `execute_sql()` in skills.
- **`run_duplicate_audit()` is mandatory after every FULL sync.** Call at STEP 8 of `omni-data-sync`.
- **`cleanup_old_raw_items()` runs after every FULL sync.** Call at STEP 8. Default retention 7d.
- **`cleanup_stale_knowledge_facts()` runs after every FULL sync.** Removes expired intel entries.
- **RLS is disabled.** Do NOT auto-enable from this skill. See SECURITY NOTE above.
- **`diplomatic_mode()` is read-only.** Never writes anywhere.
- **Vietnamese messages = same priority as English.** Always translate, never skip.
- **Feature rollup never writes to ClickUp/ADO** (v11.1). Status synchronization is Supabase-only marking. Auto-supersede requires HIGH confidence per `FEATURE_AUTOSUPERSEDE`; never supersedes Nghiem-owned pending-reply actions or GOVERNANCE_REVIEW items. Candidate features never auto-supersede until confirmed.
- **`feature_status` table is authoritative registry** after `load_feature_registry_seed()` runs once. Seed never overwrites live rows (ON CONFLICT DO NOTHING). Alias edits happen in the table, not in omni-config.

---

## FUNCTION REFERENCE TABLE

| Function | Replaces | Table |
|---|---|---|
| `write_action()` | `[ACTION]` Mem0 write | `actions` |
| `upsert_knowledge_fact()` | All atomic Mem0 tags | `knowledge_facts` |
| `get_knowledge_facts()` | `mem0_list()` + tag scan | `knowledge_facts` |
| `upsert_user_preference()` | `[COMM-STYLE]`, `[STAKEHOLDER]` Mem0 | `user_preferences` |
| `get_user_preference()` | `mem0_search()` for style | `user_preferences` |
| `list_user_preferences()` | `mem0_list()` for style | `user_preferences` |
| `upsert_project_context()` | `[PROJECT-DOC]` Mem0 writes | `project_context` |
| `get_project_docs()` | `[PROJECT-DOC][INDEX]` scan | `project_context` |
| `upsert_source_items()` | (unchanged) | `source_items` |
| `upsert_actions()` | (unchanged) | `actions` |
| `upsert_decisions()` | (unchanged) | `decisions` |
| `upsert_risks()` | (unchanged) | `risks` |
| `upsert_context_pack()` | (unchanged) | `context_packs` |
| `cache_check()` | Supabase-only, no Mem0 fallback | `sync_runs` |
| `get_context_pack()` | Supabase-only, no Mem0 fallback | `context_packs` + all tables |
| `cleanup_stale_knowledge_facts()` | `mem0_health_check()` INTEL purge | `knowledge_facts` |
| `run_duplicate_audit()` | (unchanged) | `v_duplicate_audit` view |
| `cleanup_old_raw_items()` | (unchanged) | `source_items` |
| `make_comment_external_id()` | (unchanged) | — |
| `diplomatic_mode()` | (unchanged) | — (read-only) |
| `load_feature_registry_seed()` | NEW v11.1 | `feature_status` |
| `resolve_feature_key()` | NEW v11.1 | `feature_status` (read + alias learn) |
| `rollup_feature_status()` | NEW v11.1 | `feature_status` + `actions` (supersede) |
| `get_feature_rollup()` | NEW v11.1 | `feature_status` (read) |

---

## TEST CHECKLIST — omni-utils v11.1

```
FEATURE ROLLUP TESTS (v11.1)
[ ] TC-F1  DDL applied: feature_status table + source_items.feature_key + actions.feature_key exist
[ ] TC-F2  load_feature_registry_seed() → 18 seed rows inserted; second run inserts 0 (idempotent)
[ ] TC-F3  resolve_feature_key({opco:'MM', title:'deploy customer module REP manager'}) → 'MM:customer-module'
[ ] TC-F4  resolve_feature_key with no OPCO resolvable → None (never guesses)
[ ] TC-F5  resolve_feature_key OPCO ok, no alias match → '<opco>:unmapped'
[ ] TC-F6  rollup: DEPLOY email (high conf, priority stakeholder) → status='deployed', linked open deploy-actions superseded with raw_json audit
[ ] TC-F7  rollup: DEPLOY signal medium confidence → status unchanged, conflicts[] +1
[ ] TC-F8  rollup: INFO signal → evidence appended, status NEVER changes
[ ] TC-F9  rollup: INCIDENT newer than 'deployed' → status flips to 'incident'
[ ] TC-F10 rollup never supersedes Nghiem-owned draft_reply action or GOVERNANCE_REVIEW action
[ ] TC-F11 auto-discovery: 2+ unmapped signals same OPCO + recurring phrase → candidate row; candidate auto-supersede disabled
[ ] TC-F12 get_feature_rollup() → incident/blocked sorted first; rejected rows excluded
[ ] TC-F13 build_context_pack_from_supabase() → 'feature_rollup' key present, array
```

## TEST CHECKLIST — omni-utils v11.0 (regression)

```
GUARDRAIL TESTS
[ ] TC-G1  mem0_list() → returns string "SKIPPED — Mem0 retired..."
[ ] TC-G2  mem0_add("test") → returns string "SKIPPED — Mem0 retired..."
[ ] TC-G3  mem0_update("id", "text") → returns string "SKIPPED — Mem0 retired..."
[ ] TC-G4  write_structured_cache_verbatim("[EMAILS]", "...") → returns string "SKIPPED..."
[ ] TC-G5  is_mem0_write_blocked("[INTEL]") → returns string "SKIPPED..."
[ ] TC-G6  mem0_health_check() → returns string "SKIPPED..."

SUPABASE_SQL TESTS (Fix 2)
[ ] TC-SQ1 supabase_sql("SELECT 1 AS n") → returns [{"n": 1}]
[ ] TC-SQ2 supabase_sql("SELECT * FROM nonexistent_table") → raises exception (does NOT return None)
[ ] TC-SQ3 write helper calls supabase_sql that raises → _supabase_fallback_sql() called, helper returns False

WRITE_ACTION TESTS (Fixes 1+3)
[ ] TC-A1  actions table has raw_json column (DDL applied) → INSERT succeeds
[ ] TC-A2  write_action("SYNC","COMPLETED","all done") → row in actions table confirmed
[ ] TC-A3  action_key format: 'action:SYNC:COMPLETED:2026-05-27T09:00:00:<hash8>'
[ ] TC-A4  two write_action calls same skill+type same second, different summary → 2 distinct rows (different hash)
[ ] TC-A5  two write_action calls identical skill+type+second+summary → ON CONFLICT DO NOTHING → 1 row
[ ] TC-A6  write_action(..., sync_id=valid_uuid) → sync_id column populated
[ ] TC-A7  write_action(..., module="OMS", market="VN") → module/market populated
[ ] TC-A8  write_action when supabase_sql raises → prints fallback SQL, returns False, no crash
[ ] TC-A9  metadata dict passed → stored in raw_json column

KNOWLEDGE_FACTS TESTS
[ ] TC-K1  upsert_knowledge_fact("intel_daily","intel_daily:global:2026-05-27",{...}) → row created
[ ] TC-K2  upsert same fact_key → ON CONFLICT updates, version incremented
[ ] TC-K3  upsert_knowledge_fact("intel_daily",...) → expires_at auto-set to +60d
[ ] TC-K4  upsert_knowledge_fact("intel_weekly",...) → expires_at auto-set to +90d
[ ] TC-K5  upsert_knowledge_fact("intel_pattern",...) → expires_at = NULL (never)
[ ] TC-K6  get_knowledge_facts("intel_daily") → returns rows, content is dict
[ ] TC-K7  get_knowledge_facts("intel_daily", scope="global") → scope filter applied
[ ] TC-K8  get_knowledge_facts on empty table → returns []
[ ] TC-K9  upsert_knowledge_fact with fingerprints=[...] → fingerprints array stored
[ ] TC-K10 cleanup_stale_knowledge_facts() → deletes expired rows only
[ ] TC-K11 upsert_knowledge_fact when supabase_sql raises → prints fallback SQL, returns False

USER_PREFERENCES TESTS
[ ] TC-U1  upsert_user_preference("comm_style_global","nghiem:global",{...}) → row created
[ ] TC-U2  upsert same pref_key → ON CONFLICT updates, version incremented
[ ] TC-U3  upsert_user_preference("stakeholder_profile","nghiem:Andrea",{...}) → row created
[ ] TC-U4  get_user_preference("comm_style_global","nghiem:global") → returns row
[ ] TC-U5  get_user_preference on missing key → returns None
[ ] TC-U6  list_user_preferences("stakeholder_profile") → returns all stakeholder rows

PROJECT_CONTEXT TESTS
[ ] TC-P1  upsert_project_context("OMNIHighLevel","/mnt/...",hash,...) → row created
[ ] TC-P2  upsert same file_stem with new hash → ON CONFLICT updates hash + updated_at
[ ] TC-P3  get_project_docs("OMNIHighLevel") → returns single row
[ ] TC-P4  get_project_docs() → returns all rows
[ ] TC-P5  get_project_docs on empty table → returns []

CACHE_CHECK TESTS
[ ] TC-C1  cache_check() after recent sync → mode="CACHE", degraded=False
[ ] TC-C2  cache_check() on empty DB → mode="LIVE", hit_type="supabase_cache_check_missing"
[ ] TC-C3  cache_check() when supabase_sql raises → mode="LIVE", degraded=True, hit_type="supabase_unavailable"
[ ] TC-C4  cache_check() — NO Mem0 call attempted under any circumstance

DECISIONS STATUS TESTS (Fix 5)
[ ] TC-DS1 upsert_decisions with status="rejected" → accepted, row created
[ ] TC-DS2 upsert_decisions with status="confirmed" → accepted
[ ] TC-DS3 upsert_decisions with status="bad_value" → defaulted to 'unclear', WARNING logged
[ ] TC-DS4 DB CHECK constraint allows 'rejected' (DDL patch applied if needed)

GET_CONTEXT_PACK TESTS (Fix 4)
[ ] TC-X1  get_context_pack("briefing") → source="supabase"
[ ] TC-X2  get_context_pack("briefing") with sb_pack warnings → degraded=True (not hardcoded False)
[ ] TC-X3  get_context_pack("briefing") with freshness.status="partial" → preserved in output
[ ] TC-X4  get_context_pack("briefing") when Supabase fails → degraded=True, empty lists, no crash
[ ] TC-X5  get_context_pack — NO Mem0 call attempted under any circumstance
[ ] TC-X6  get_context_pack("briefing") → data.client_facing_open_actions present
[ ] TC-X7  get_context_pack("briefing") → data.waiting_on_client also present (legacy alias, same list)

CLIENT_FACING ACTIONS TESTS (Fix 6)
[ ] TC-CF1 build_context_pack_from_supabase() → returns "client_facing_open_actions" key
[ ] TC-CF2 build_context_pack_from_supabase() → returns "waiting_on_client" key as legacy alias
[ ] TC-CF3 rows in client_facing_open_actions have "owner_label" field (not "waiting_for")
[ ] TC-CF4 no row is labelled "waiting on client" unless waiting_for_type column says 'client'

SYNC RUN TESTS
[ ] TC-S1  create_sync_run("FULL") → returns UUID, row in sync_runs
[ ] TC-S2  complete_sync_run(id, "complete", [...], [], "done") → status updated
[ ] TC-S3  get_latest_sync_run() → most recent row returned
[ ] TC-S4  get_latest_sync_run() on empty DB → returns None

DUPLICATE AUDIT TESTS
[ ] TC-D1  run_duplicate_audit() → returns {total_duplicates, clean, by_table}
[ ] TC-D2  run_duplicate_audit() with clean tables → clean=True, total_duplicates=0
[ ] TC-D3  run_duplicate_audit includes knowledge_facts in by_table dict
```

---

## FUTURE ARCHITECTURE NOTE

Google Drive JSON export is an **optional audit backup only** — not a primary cache path.

When needed (e.g. post-EOD audit trail):
```
/Daily Brief/YYYY-MM-DD/context-pack-briefing.json
/Daily Brief/YYYY-MM-DD/context-pack-eod.json
/ADO Sync/YYYY-MM-DD/ado-sync-result.json
```

Write via Google Drive MCP after Supabase upsert completes. Never block on Drive write failure.
