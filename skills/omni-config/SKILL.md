---
name: omni-config
version: "1.15"
description: "Centralized config for all OMNI skills. READ-ONLY — never execute directly. All skills read this file first to get shared constants: stakeholders, modules, OPCOs, Teams/ClickUp IDs, cache thresholds, signal taxonomy, Vietnamese keywords, FEATURE_REGISTRY (OPCO+feature rollup seed), §18 AUTONOMOUS SCHEDULE + intraday pulse job + EVENT_TICKS event-reaction contract (read by omni-orchestrator), and §19 PATCH_AUTOMERGE_POLICY (safety contract for git-native skill-patch PRs + tiered auto-merge, read by omni-operator-learning). One edit here updates all skills. Version: CONFIG_VERSION = '1.15'."
---

# OMNI Shared Configuration

**Purpose:** Single source of truth for all constants shared across OMNI skills.
**Read by:** Every OMNI skill before executing — read this file at STEP 0 before reading omni-utils.
**Rule:** Never hardcode these values in individual skill files. Reference this config only.

---

## VERSION CONTRACT

```python
CONFIG_VERSION = "1.15"
# Increment on every edit. Consumer skills should log which version they last tested against.
```

**Changelog:**

| Version | Change |
|---|---|
| 1.15 | **Register omni-orchestrator 1.1 — event-tick lock-step (2026-06-25).** Registry-only bump accompanying the Stage-2 ship of `omni-orchestrator` v1.1 (adds `trigger='event'` handling that reads the §18 `EVENT_TICKS` contract added in 1.14). `EXPECTED_SKILL_VERSIONS`: omni-orchestrator **1.0→1.1**, config self-row **1.14→1.15**. No constants/logic changed (§18 EVENT_TICKS already shipped in 1.14). Kept in lock-step so the drift audit stays clean once both files are uploaded together. |
| 1.14 | **§18 Intraday auto-trigger + EVENT_TICKS contract (2026-06-25).** P1 of the always-on operator. (a) Added a third `SCHEDULE` job `intraday` (08:00–18:30, any weekday) running a staleness-gated LIGHTWEIGHT `sync_intraday` step then `pulse` — so on each hourly cron tick the agent self-refreshes only when cache is stale (gate `INTRADAY_SYNC_GATE_H=3`) and always surfaces a read-only focus pulse. Cadence is set by a new external **OMNI-Pulse** hourly routine; needs **ZERO orchestrator code change** — `compute_plan` already iterates `SCHEDULE` generically and pulse/sync are not `once_per_day`. (b) Added declarative `EVENT_TICKS` block — the spec for event-driven reactions (P0 incident, client email, governance comment) the orchestrator implements in Stage 2 (v1.1): each event names a detection source, an ordered fast-path, and inherits the SAME governance guard (draft/surface only, never send/commit). (c) `SCHEDULE_TICK_CHECKS`+`SCHEDULE_RULES` gain intraday/event notes. Frontmatter version reconciled 1.12→**1.14** (was stale vs CONFIG_VERSION). `EXPECTED_SKILL_VERSIONS` self-row 1.13→**1.14**; `omni-orchestrator` deliberately held at 1.0 (registers to 1.1 only when its Stage-2 SKILL.md ships — established hold pattern, no false drift). No other skill constants/logic changed. |
| 1.13 | **§19 Skill Patch Auto-Merge Policy (2026-06-24).** Added Section 19 `PATCH_REPO` / `PATCH_TIERS` / `PROTECTED_PATCH_FILES` / `PROTECTED_PATCH_CONTENT` / `PATCH_AUTOMERGE_POLICY` / `AUTOMERGE_ENABLED` — the safety contract for the git-native self-update loop (`omni-operator-learning` v1.3, shipping next). Tier 0 behavioral `operator_rule`s unchanged (no git). Tier 1 = single non-protected skill, ≤40 changed lines / 1 file, occ≥3, auto-merge ONLY on a green `omni-skill-eval` check (≤3/week). Tier 2 = omni-utils / omni-config / omni-orchestrator / governance / multi-file → PR only, human merge. Branch safety stays ON (`claude/` prefix — never push to `main`); circuit breaker disables auto-merge after 2 consecutive degrading eval-score trends. Config self-row 1.12→**1.13**. `omni-operator-learning` NOT yet registered to 1.3 — registers when its SKILL.md ships (established hold pattern), so no false drift row. No constants/logic changed for any existing skill. |
| 1.12 | **Registry reconcile — register omni-orchestrator + fix config self-row (2026-06-24).** `EXPECTED_SKILL_VERSIONS`: omni-config self-row 1.9→**1.12** (was never advanced when config went 1.10→1.11) and added **omni-orchestrator 1.0** (held back until its SKILL.md shipped; now live and running as a cloud routine). Registry-only edit — no constants/logic changed. Clears the two drift rows the first routine tick surfaced; drift audit should now report 0. |
| 1.11 | **Loop v3 recall registration (2026-06-23).** Registered `omni-operator-learning` 1.1→**1.2** (new STEP 1C Recall Mining: scores recall of materialized incidents flagged-ahead vs missed, promotes vigilance-only 'flag earlier' rules for recurring misses). Added §10B `LEARNING_RECALL_LEAD_MIN_DAYS = 1`. No other constants/logic changed; recall reuses the `calibration` fact + `operator_rule` (no new table). `omni-orchestrator` still pending registration until its file ships. |
| 1.10 | **§18 Autonomous Schedule + agent_runs (2026-06-23).** Added Section 18 `SCHEDULE` / `SCHEDULE_TICK_CHECKS` / `SCHEDULE_RULES` — the declarative schedule the new `omni-orchestrator` agent brain reads each tick to decide what is due (morning sync+briefing, evening sync+EOD+briefing, Monday weekly learning), with idempotency (done-today via `agent_runs`), staleness gates, fail-open, and a hard governance guard (orchestrator never sends external comms / never commits scope-capacity-SOW). Companion Supabase table `agent_runs` (heartbeat + idempotency + next_due_at ledger) created same day — RLS off by design, structurally separate from `actions`. No existing constants/logic changed; `EXPECTED_SKILL_VERSIONS` not yet touched (omni-orchestrator registers when its SKILL.md ships). |
| 1.9 | **Registry drift clear — full sync to on-disk (2026-06-21).** Updated `EXPECTED_SKILL_VERSIONS` to match authoritative on-disk versions, clearing all 6 false-positive drift rows the weekly learning audit flagged plus the 3 skills patched in the decision-dedup chain: omni-utils 11.1→**11.2** (context-pack builder filters `superseded_by IS NULL`), omni-data-sync 12.2→**12.5** (STEP 7A-DEDUP structural duplicate-decision merge), omni-eod-review 9.3→**9.4** (pattern-mining query filters `superseded_by IS NULL`), omni-pulse 1.0→**1.1**, omni-clickup-ado-sync 6.3→**6.5**, omni-self-improve 1.1→**1.2**, omni-operator-learning 1.0→**1.1**, and omni-config self-row 1.6→**1.9** (registry had not been advanced since 1.6 despite config reaching 1.8). Registry-only edit — no constants/logic changed. After this, the drift audit should report 0 items. |
|---|---|
| 1.8 | **P4 cleanup.** Registry: omni-self-improve 1.0→1.1 (gate token fix — now detects `skill IN ('EOD','BRIEFING') AND action_type='REVIEWED'`). Closed the last two in-skill handshake-annotation mismatches in the same pass: omni-data-sync and omni-clickup-ado-sync stale `CONFIG_VERSION`/`UTILITY_VERSION` "tested-against" lines corrected to current (1.8 / 11.1) — annotation-only, no logic change, so those two skills keep their own versions (12.2 / 6.3) to avoid cascading drift into eod/briefing dependency notes. |
| 1.7 | **Self-improve hook wired (P2/P3).** Registry bumped for the two skills that now invoke the post-run auto-train hook as their final step: omni-eod-review 9.2→9.3 (STEP 6), omni-daily-briefing 7.2→7.3 (STEP 8). Hook = behavioral tier only (promote operator_rule), fail-open, never edits SKILL.md. Registry kept in lock-step so the drift audit stays clean. |
| 1.6 | **Registry drift fix + self-improve registration.** Corrected `EXPECTED_SKILL_VERSIONS` to match authoritative on-disk versions: omni-utils 11.0→11.1, omni-data-sync 12.0→12.2, omni-daily-briefing 7.1→7.2, omni-eod-review 9.1→9.2, omni-pulse "current"→"1.0". These rows were stale and would have thrown false-positive drift in the learning audit. Registered new skill `omni-self-improve` (1.0) for the post-run auto-train hook (P1). NOTE: in-skill version handshake references are still stale in omni-data-sync (line ~62: UTILITY_VERSION "11.0") and omni-clickup-ado-sync (CONFIG_VERSION "1.3", UTILITY_VERSION "11.0") — flagged for a later per-skill phase, not touched here (one skill at a time). |
| 1.5 | **Feature Status Rollup foundation.** Added Section 17: `FEATURE_REGISTRY` (seeded OPCO+feature entities with alias keywords), `FEATURE_STATUS_PRECEDENCE`, `FEATURE_AUTOSUPERSEDE` rules, feature_key resolution rules, and auto-discovery config. Added optional `feature_key` field to NormalizedSignal schema. Registry seed is bootstrap-only — runtime registry lives in Supabase `feature_status` table (DDL ships in omni-utils v11.1) and grows daily via sync auto-discovery. **Fix:** added SA (South Africa) to OPCOS — was missing despite active SA scope (LOOP OTP, Eazle rebrand, env setup, Aug pilot). |
| 1.3 | Added `PENDING_DECISION` and `GOVERNANCE_REVIEW` to `ACTION_VALID_SKILLS`. Added three-register decision routing comments: `[ACTION][DECISION]` = confirmed only; `[ACTION][PENDING_DECISION]` = proposed/client/pending/assumption; `[ACTION][GOVERNANCE_REVIEW]` = SOW/capacity/commercial/ownership. Added morning briefing display rules per register. |
| 1.2 | Added `clickup_comments_light` to `LIGHTWEIGHT_SOURCES`. Updated LIGHTWEIGHT mode description in `SYNC_MODES`. ClickUp comment extraction now runs incrementally in daily LIGHTWEIGHT sync (tasks updated since last sync only). |
| 1.1 | Updated SYNC_MODES: added `sent` and `sent_historical` sources. Added sent-analyzer cache thresholds: CACHE_SENT_DAILY_H, CACHE_SENT_HIST_DAYS. Added ACTION_VALID_SKILLS entry for SENT_ANALYSIS. |
| 1.0 | Initial extraction from omni-data-sync, omni-daily-briefing, omni-eod-review. |

---

## 1. PROGRAM IDENTITY

```python
PROGRAM = "OMNI"
PM = "Nghiem Tan Nguyen"
ORG = "Niteco Group"
CLIENT = "Heineken APAC"
TIMEZONE = "Asia/Bangkok"   # GMT+7
USER_ID = "nghiem"   # Supabase row owner key (Mem0 retired)
```

---

## 2. CACHE THRESHOLDS (authoritative — used by cache_check() in omni-utils)

```python
# All times in hours. cache_check() reads these — do NOT redefine in any skill.
CACHE_FRESH_H   = 2    # < 2h → CACHE mode — use Supabase context pack directly, skip live fetch
CACHE_WARN_H    = 5    # 2–5h → WARN mode — stale but usable, surface warning
CACHE_DEAD_H    = 72   # > 72h → LIVE mode + Gap warning

# Per-skill overrides (pass as stale_threshold_h to get_context_pack / cache_check)
CACHE_BRIEFING_H  = 6   # Daily briefing: cache acceptable up to 6h old
CACHE_EOD_H       = 12  # EOD review: cache acceptable up to 12h old
CACHE_ESCALATION_H = 2  # Escalation: must be fresh (2h)
CACHE_ADO_SYNC_H  = 12  # ADO sync: acceptable up to 12h old

# Sent analyzer thresholds
CACHE_SENT_DAILY_H   = 6    # Re-run daily sent analysis if > 6h old
CACHE_SENT_HIST_DAYS = 30   # Re-run historical scan if > 30 days old
```

**Rules:**
- `cache_check()` in `omni-utils` reads `CACHE_WARN_H` and `CACHE_DEAD_H` from here.
- Each skill passes its own `stale_threshold_h` override to `get_context_pack()`.
- Never redefine thresholds in skill files — edit here only.

---

## 3. SYNC MODES (authoritative)

```python
SYNC_MODES = {
    "CACHE":       "No source fetch — read Supabase context pack only",
    "LIGHTWEIGHT": "Inbox + Sent (24–72h) + Teams + ClickUp comment signals (incremental) — fast operational refresh",
    "FULL":        "Inbox + Sent + Teams + ClickUp + Calendar — standard daily run",
    "DEEP":        "FULL + Sent historical 3-month scan + ADO + project docs — monthly/manual",
}

# Which sources each mode fetches
LIGHTWEIGHT_SOURCES = ["inbox", "sent", "teams", "clickup_comments_light"]
FULL_SOURCES        = ["inbox", "sent", "teams", "clickup", "calendar"]
DEEP_SOURCES        = ["inbox", "sent", "sent_historical", "teams", "clickup", "calendar", "ado", "project_docs"]
```

---

## 4. ACTIVE OPCOs

```python
OPCOS = ["MY", "ID", "KH", "LA", "TW", "IN", "MM", "SA"]
OPCO_FULL = {
    "MY": "Malaysia",
    "ID": "Indonesia",
    "KH": "Cambodia",
    "LA": "Laos",
    "TW": "Taiwan",
    "IN": "India",
    "MM": "Myanmar",
    "SA": "South Africa",
}
```

---

## 5. MODULES

```python
MODULES = ["OMNI", "REP", "LOOP", "HAP", "PEM", "OMS", "CC", "REP_MGR"]
MODULE_FULL = {
    "OMNI": "OMNI Core / OMS",
    "REP":  "Route Execution Platform",
    "LOOP": "Last-Mile Delivery",
    "HAP":  "Heineken Access Platform",
    "PEM":  "Promotion & Execution Management",
    "OMS":  "Order Management System",
    "CC":   "Contact Center",
    "REP_MGR": "REP Manager",
}
```

---

## 6. STAKEHOLDERS

```python
# Priority senders — always flag regardless of content
PRIORITY_STAKEHOLDERS = [
    "Andrea Cervellin",
    "Kay Sheng Hong",
    "Kezia Koen",
    "Angelia Ooi",
    "Zach",
    "HtunKhaing Lynn",
    "Michelle Meng",
    "Kinneth Chhorn",
    "Tan Vu",
    "Hung Nguyen",
    "Hoang Ngo",
    "Huy Phan",
]

# FieldAssist contacts
FIELDASSIST_CONTACTS = ["Achintya", "Prithvi", "Siddharth", "Chitransh"]
PARALLELDOTS_CONTACTS = ["Kartik"]
UB_INDIA_CONTACTS = ["Dhiraj", "Deepak", "Rittu"]

# Governance actors (always flag, always translate VN messages mentioning these)
GOVERNANCE_ACTORS = ["Andrea", "Yilun", "Peter", "Ha Hoang", "Huy Phan"]

# Communication protocol:
# - Andrea: NEVER contact directly from delivery team
# - Channel: Delivery → Ha Hoang (PMO) → YiLun → Andrea (Peter CC always)
ANDREA_COMM_CHANNEL = "YiLun only (Peter CC)"
```

---

## 7. TEAMS CHAT IDs

```python
TEAMS_CHATS = {
    "VN-OMNI-GOV": {
        "id":  "19:d9f895cfc1794e678a6d289a1392e992@thread.v2",
        "uri": "teams:///chats/19%3Ad9f895cfc1794e678a6d289a1392e992%40thread.v2/messages",
        "note": "Primarily Vietnamese — always translate",
    },
    "Nghiem-HuyPhan": {
        "id":  "19:8e31c820-093c-4254-836d-6938399ea304_d3c599a6-fc79-4a2e-b9d0-0c9495d666b4@unq.gbl.spaces",
        "uri": "teams:///chats/19%3A8e31c820-093c-4254-836d-6938399ea304_d3c599a6-fc79-4a2e-b9d0-0c9495d666b4%40unq.gbl.spaces/messages",
        "note": "Direct chat — PMO alignment",
    },
}

# CRITICAL Teams API quirk — do NOT change this:
TEAMS_SEARCH_QUERY = "OMNI"   # broad single-word only; specific keywords return empty
```

---

## 8. CLICKUP IDs

```python
CLICKUP_TEAM_ID  = "90182383427"
CLICKUP_SPACE_ID = "90189534670"
CLICKUP_USER_ID  = "107626012"   # Nghiem's ClickUp user ID

CLICKUP_LISTS = {
    "OMNI":            "901815590005",
    "REP":             "901815589958",
    "PROMO":           "901815507660",
    "LOOP":            "901815590042",
    "HAP":             "901815590114",
    "CC":              "901815590134",
    "REP_MGR":         "901815590147",
    "OTHER":           "901815590161",
}
```

---

## 9. AZURE DEVOPS

```python
ADO_ORG     = "https://dev.azure.com/NitecoGroup/"
ADO_PROJECT = "Heineken"
ADO_AREA    = r"Heineken\OMS"
ADO_ITERATION = r"Heineken\OMS\Kanban"

ADO_PROMO_PROJECT  = "Heineken.0K9.TPM-POC"   # PROMO list tasks sync here
ADO_PROMO_WORKITEM = "Product Backlog Item"
ADO_DEFAULT_WORKITEM = "User Story"

# PAT location — read at runtime; never hardcode the value
ADO_PAT_FILE = r"C:\Users\tamqu\Documents\Claude\Projects\W\.secrets\ado_pat.txt"
```

---

## 10. SKILL VERSION REGISTRY (authoritative — used for drift handshake)

# ⛔ Mem0 is retired — legacy entry IDs removed in CONFIG 1.4.
# Every skill MUST compare its own on-disk version against this registry at STEP 0.
# On mismatch: print "⚠️ VERSION DRIFT: <skill> on-disk v<X> ≠ registry v<Y> — re-upload latest export"
# and continue (do not abort). omni-operator-learning audits drift weekly.

EXPECTED_SKILL_VERSIONS = {
    "omni-config":                  "1.15",
    "omni-orchestrator":            "1.1",
    "omni-utils":                   "11.2",
    "omni-data-sync":               "12.5",
    "omni-email-extractor":         "4.0",
    "omni-sent-analyzer":           "2.0",
    "omni-daily-briefing":          "7.3",
    "omni-eod-review":              "9.4",
    "omni-pulse":                   "1.1",
    "omni-comment-reply-queue":     "3.0",
    "omni-clickup-ado-sync":        "6.5",
    "ado-oms-knowledge-sync":       "2.1",
    "project-knowledge-sync":       "2.0",
    "requirement-analyzer-compact": "4.0",
    "draft-email-skill":            "5.0",
    "omni-ai-operator-eval-review": "2.1",
    "omni-operator-learning":       "1.2",
    "omni-self-improve":            "1.2",
}

## 10B. OPERATOR LEARNING CONFIG (used by omni-operator-learning)

LEARNING_RULE_PROMOTION_MIN_OCCURRENCES = 2     # eval/feedback issue seen ≥2× → promote to operator_rule
LEARNING_FEEDBACK_EXPIRY_DAYS           = 90    # operator_feedback facts expire after 90d
LEARNING_LOOKBACK_DAYS                  = 14    # aggregation window for weekly learning run
LEARNING_MAX_ACTIVE_RULES               = 25    # cap injected operator_rules (highest-severity first)
LEARNING_RECALL_LEAD_MIN_DAYS           = 1     # Loop v3 recall: a prior flag counts as "ahead" only if >=1 day before the incident; <1d = "late"
# knowledge_facts fact_types owned by the learning loop:
#   operator_feedback — user corrections captured in-chat (expiry 90d)
#   operator_rule     — promoted durable prevention rules (no expiry)

## 11. GOOGLE DRIVE FOLDER IDs

```python
GDRIVE_FOLDERS = {
    "Daily Brief": "1ot0ormfShDHzk0Soch2dYM6fu57tsgmn",
    "ADO Sync":    "1yaEZTxoZB_pwocWK124KWN5fAH_RSh-E",
}
```

---

## 12. SIGNAL TAXONOMY

```python
# Primary signal types — used by email extractor, Teams extraction, EOD review
SIGNAL_TYPES = ["DECISION", "BLOCKER", "URGENT", "DEPLOY", "DIRECTION", "INFO", "INCIDENT", "APPROVAL"]

SIGNAL_RULES = {
    "DECISION":  "Direction given, alignment confirmed, scope agreed, approval granted",
    "BLOCKER":   "Work stopped, waiting on someone, prod issue, unresolved dependency",
    "URGENT":    "Explicit urgency, deadline today/tomorrow, escalation, P1 mention",
    "DEPLOY":    "Release, go-live, prod push, cutover, environment promotion",
    "DIRECTION": "Senior stakeholder (Andrea/Peter/YiLun/Kezia/KaySheng) giving instructions",
    "INCIDENT":  "Production incident, data issue, system down",
    "APPROVAL":  "Explicit approval request or grant",
    "INFO":      "Default — relevant but no immediate action",
}
```

---

## 13. KEYWORD TRIGGERS

```python
# English ops/tech keywords → flag for signal extraction
KEYWORDS_OPS = [
    "OMNI", "REP", "LOOP", "HAP", "OMS",
    "deployment", "deploy", "bug", "urgent", "blocked",
    "prod", "production", "incident", "go-live", "release",
]

# English finance/capacity keywords → flag + governance sensitivity
KEYWORDS_CAPACITY = [
    "PEM", "budget", "FTE", "capacity", "absorb", "burst",
    "cost", "contract", "invoice", "scope", "quote", "SOW", "estimate",
]

# Andrea scope-creep detection → always flag, route through YiLun
KEYWORDS_SCOPE_CREEP = [
    "can we add", "how hard would it be", "not prioritized but",
    "while we're at it", "quick addition", "small change",
]

# Vietnamese keywords → translate + flag (same priority as English)
KEYWORDS_VIETNAMESE = [
    "khách",        # client/customer issue
    "nhạy cảm",     # sensitive
    "align",
    "full picture",
    "estimate",
    "communicate",
    "deploy",
    "ticket",
    "SOW", "FTE", "ADO", "JIRA",
    "scale down",
    "resource",
    "capacity",
    "deadline",
    "Peter", "YiLun", "Andrea",
    # "anh/chị" + action verb = senior giving direction
]

# Sent email commitment language — used by omni-sent-analyzer filter
KEYWORDS_COMMITMENT = [
    "I will", "we will", "I can", "we can",
    "by tomorrow", "by Friday", "by end of week", "next week",
    "I'll check", "we'll confirm", "I'll follow up", "will come back",
    "will share", "will send", "will provide", "will update",
]

# Sent email decision language — used by omni-sent-analyzer filter
KEYWORDS_DECISION = [
    "we agreed", "confirmed", "decision", "finalized", "approved",
    "not proceed", "we should", "we suggest", "I suggest", "I recommend",
    "aligned on", "proceed with", "go ahead with",
]
```

---

## 14. ACTION LOG CONFIG

```python
ACTION_ENTRY_SIZE_CAP = 2000    # chars — split to overflow if exceeded
ACTION_VALID_SKILLS   = ["EMAIL", "REQ", "BRIEFING", "EOD", "ADO_SYNC", "DECISION",
                          "SENT_ANALYSIS", "PENDING_DECISION", "GOVERNANCE_REVIEW"]
ACTION_VALID_TYPES    = ["SENT", "CAPTURED", "REVIEWED", "SYNCED", "RECORDED", "SENT_ANALYSIS"]

# Tag format: [ACTION][<SKILL>][YYYY-MM-DD] — one entry per skill per day
# Overflow:   [ACTION][<SKILL>][YYYY-MM-DD][N] — suffix when cap hit
#
# Decision register — THREE REGISTERS (v6.0):
# [ACTION][DECISION][DATE]           — confirmed decisions only (ownership + scope + next step accepted)
# [ACTION][PENDING_DECISION][DATE]   — proposed/client_request/pending_internal/assumption_timeline
# [ACTION][GOVERNANCE_REVIEW][DATE]  — SOW, capacity, commercial scope, ownership changes (any class)
#
# Morning briefing display rules:
# [ACTION][DECISION]          → show under "Decisions"
# [ACTION][PENDING_DECISION]  → show under "Pending Alignment / Decision Needed"
# [ACTION][GOVERNANCE_REVIEW] → show under "⚠️ Governance-sensitive — do not externally confirm until internally aligned"
```

---

## 15. RESOURCE PLAN (current)

```python
RESOURCE_PLAN = {
    "total_fte": 11.25,
    "OMS":     "675%",
    "REP_LOOP": "450%",
    "PEM":     "0% (stopped)",
    "notes":   "Son on separate SOW. No designer assigned.",
}
```

---

## 16. NORMALIZED SIGNAL SCHEMA

**Purpose:** Every extracted item — from email, Teams, ClickUp, or ADO — is converted into a
`NormalizedSignal` object BEFORE being written to Supabase or passed downstream.
This ensures all skills speak the same language when reading signals.

```python
# ── NormalizedSignal — canonical object for every extracted signal ──────────

NORMALIZED_SIGNAL_SCHEMA = {
    # REQUIRED FIELDS — must be present on every signal
    "signal_id":   "<source_prefix>-<YYYYMMDD>-<hash4>",
    "source":      "<EMAIL | TEAMS | CLICKUP | ADO>",
    "source_id":   "<original system ID or 'unknown'>",
    "ts":          "<YYYY-MM-DD HH:MM GMT+7>",
    "actor":       "<display name of sender/author/reporter>",
    "signal":      "<DECISION | BLOCKER | URGENT | DEPLOY | DIRECTION | INCIDENT | APPROVAL | INFO>",
    "summary":     "<≤25 words: ACTOR [verb] WHAT. Action: [next step] or none.>",
    "module":      "<REP | LOOP | HAP | PEM | OMS | CC | OMNI | null>",
    "opco":        "<MY | ID | KH | LA | TW | IN | MM | ALL | null>",
    "next_action": "<specific action required, or null>",
    "owner":       "<Nghiem | team member name | null>",
    "status":      "<active | resolved | ignored>",
    "confidence":  "<high | medium | low>",

    # OPTIONAL — v1.5 Feature Rollup
    "feature_key": "<'<OPCO>:<feature-slug>' resolved via Section 17, or null if unresolved>",
}

EMAIL_EXTRA_FIELDS = {
    "fp":             "<fingerprint: domain|subject_norm|YYYYMMDD>",
    "from_email":     "<sender email address>",
    "to_type":        "<direct | cc>",
    "subject":        "<cleaned subject — no Re:/Fwd:/[external]>",
    "primary_tag":    "<[URGENT] | [DEPLOY] | [DECISION] | [APPROVAL] | [INCIDENT] | [INFO]>",
    "secondary_tags": ["<[OPCO:XX]>", "<[MODULE:XX]>", "<[CAPACITY]>", "<[GOVERNANCE]>"],
}

TEAMS_EXTRA_FIELDS = {
    "chat":        "<VN-OMNI-GOV | Nghiem-HuyPhan | Direct | GroupName>",
    "translated":  "<True | False>",
}

CLICKUP_EXTRA_FIELDS = {
    "task_id":   "<ClickUp task ID>",
    "list":      "<OMNI | REP | LOOP | HAP | PROMO | CC | REP_MGR | OTHER>",
    "priority":  "<urgent | high | normal | low | null>",
    "due_date":  "<YYYY-MM-DD | null>",
    "cu_status": "<ClickUp task status string>",
    "assignee":  "<assignee display name | null>",
}

ADO_EXTRA_FIELDS = {
    "work_item_id":   "<ADO work item ID>",
    "work_item_type": "<User Story | Bug | Task | Product Backlog Item>",
    "ado_status":     "<ADO pipeline status string>",
    "area_path":      "<ADO area path string>",
}
```

### Source → signal mapping

| Source | `signal` mapping | `actor` field | `ts` field |
|---|---|---|---|
| Email | primary_tag stripped of brackets → signal type | `from_name` | email received time |
| Teams | signal field already set in STEP 3D extraction | `sender` | message timestamp |
| ClickUp | overdue/urgent → `URGENT`; stale high-pri → `BLOCKER`; other active → `INFO` | `assignee` or `"unassigned"` | `last_updated` |
| ADO | ReadyProd/AccEnv bug → `BLOCKER`; OnProd story → `INFO`; Done → `INFO` | `assignee` | `changed_date` |

### Confidence scoring rules

```python
def assign_confidence(signal_obj: dict) -> str:
    sig = signal_obj.get("signal")
    src = signal_obj.get("source")
    if sig in ("DECISION", "INCIDENT", "DEPLOY"):
        return "high"
    if sig == "URGENT" and src in ("EMAIL", "TEAMS"):
        return "high"
    if sig == "BLOCKER" and signal_obj.get("owner"):
        return "high"
    if sig == "INFO":
        return "low"
    if sig in ("URGENT", "BLOCKER") and src == "CLICKUP" and not signal_obj.get("due_date"):
        return "low"
    return "medium"
```

### Compact serialization format (display/log lines only — storage is Supabase JSON)

```
sig:<signal_id> | src:<source> | type:<signal> | conf:<confidence> | ts:<ts> | actor:<actor> | opco:<opco|-> | mod:<module|-> | owner:<owner|-> | status:<status> | <summary ≤25w>
```

---

## 17. FEATURE REGISTRY & ROLLUP CONFIG (v1.5)

**Purpose:** Entity layer that links signals from ALL sources (email, Teams, ClickUp tasks,
ClickUp comments, ADO) to a single `(OPCO, Feature)` key so status is centralized and
synchronized, never fragmented per source.

**Runtime registry lives in Supabase `feature_status` table** (DDL in omni-utils v11.1).
The dict below is the BOOTSTRAP SEED only — loaded once, then the table is authoritative
and grows daily via auto-discovery during sync.

```python
# ── feature_key format ───────────────────────────────────────────────────────
# "<OPCO>:<feature-slug>"   e.g. "MM:customer-module", "ID:oms-fina"
# OPCO ∈ OPCOS (Section 4) or "ALL" for cross-market features.

# ── Bootstrap seed (one-time load into feature_status; table wins after that) ─
FEATURE_REGISTRY_SEED = {
    # ── MM ──
    "MM:customer-module":   {"module": "REP",  "label": "MM Customer Module",
        "aliases": ["customer module", "rep manager", "new backend perfect outlet",
                    "ir offline", "perfect outlet backend"]},
    "MM:hap-phase1":        {"module": "HAP",  "label": "MM HAP Phase 1",
        "aliases": ["hap phase 1", "hap acc", "hap deployment", "hap go-live"]},
    "MM:infra-migration":   {"module": "OMNI", "label": "MM Infra Migration",
        "aliases": ["mm infra", "infra migration"]},

    # ── ID ──
    "ID:oms-fina":          {"module": "OMS",  "label": "ID OMS FINA",
        "aliases": ["fina", "chg2331596", "fina prod regression"]},
    "ID:chub-integration":  {"module": "OMS",  "label": "ID CHUB Integration",
        "aliases": ["chub"]},
    "ID:dbb-solace":        {"module": "OMS",  "label": "ID DBB Solace",
        "aliases": ["dbb", "solace", "sem blackout"]},

    # ── TW ──
    "TW:perfect-outlet":    {"module": "REP",  "label": "TW Perfect Outlet",
        "aliases": ["tw perfect outlet", "perfect outlet acc", "perfect outlet prod"]},
    "TW:master-data":       {"module": "OMS",  "label": "TW Master Data Cleanup",
        "aliases": ["master data cleanup", "tw master data"]},

    # ── SA ──
    "SA:loop-otp":          {"module": "LOOP", "label": "SA LOOP OTP",
        "aliases": ["loop sa otp", "sa otp", "otp issue"]},
    "SA:eazle-rebrand":     {"module": "OMNI", "label": "SA Eazle/OMNI Rebrand",
        "aliases": ["eazle", "login page rebrand", "login rebrand"]},
    "SA:env-setup":         {"module": "OMNI", "label": "SA Branch/Env Setup",
        "aliases": ["sa branch", "sa environment", "sa env setup"]},
    "SA:multicategory":     {"module": "REP",  "label": "SA Multicategory Filter",
        "aliases": ["multicategory filter", "multi-category"]},

    # ── MY ──
    "MY:contract-module":   {"module": "REP",  "label": "MY Contract Module",
        "aliases": ["contract module", "con-", "sponsorship", "proposal letter",
                    "auto-renewal", "e-signature"]},
    "MY:tpm-promo":         {"module": "PEM",  "label": "MY TPM/PROMO",
        "aliases": ["tpm", "promo scope", "scope clarification", "efunction"]},
    "MY:product-hierarchy": {"module": "OMS",  "label": "MY Product Hierarchy",
        "aliases": ["product hierarchy"]},

    # ── LA ──
    "LA:customer-master":   {"module": "OMS",  "label": "LA Customer Master",
        "aliases": ["la customer master", "customer master"]},
    "LA:glassrun":          {"module": "LOOP", "label": "LA GlassRun Integration",
        "aliases": ["glassrun", "glass run"]},

    # ── IN ──
    "IN:otp-provider":      {"module": "REP",  "label": "India OTP Provider",
        "aliases": ["otp provider", "twilio", "india otp"]},
    "IN:acc-deployment":    {"module": "REP",  "label": "India ACC Deployment",
        "aliases": ["india acc", "rep india", "india deployment"]},
}

# ── Resolution rules (used by resolve_feature_key() in omni-utils v11.1) ─────
FEATURE_RESOLUTION = {
    "opco_order": [
        "explicit market/opco field on signal",
        "OPCO code or country name in subject/title/list name",
        "OPCO of the ClickUp task a comment belongs to",
        "null → feature_key unresolvable (OPCO is mandatory)",
    ],
    "feature_order": [
        "alias match (case-insensitive, longest-alias-first) within resolved OPCO",
        "alias match against ALL-opco features",
        "no match → auto-discovery candidate (see below)",
    ],
    "tie_break": "longest matching alias wins; if equal, higher-precedence signal source (EMAIL > TEAMS > CLICKUP > ADO)",
}

# ── Auto-discovery (registry grows day by day) ───────────────────────────────
FEATURE_AUTODISCOVERY = {
    "min_signals_for_candidate": 2,      # ≥2 signals same OPCO + recurring noun-phrase → candidate row
    "candidate_registry_state":  "candidate",   # surfaced in EOD review for Nghiem confirm/merge/reject
    "confirmed_registry_state":  "confirmed",
    "seeded_registry_state":     "seeded",
    "alias_autolearn": "when a signal resolves to a feature via fuzzy/partial match, append the new phrase to aliases[]",
    "unresolved_fallback": "<OPCO>:unmapped — counted, never status-rolled",
}

# ── Status precedence (latest-wins within tier; tier beats recency ≤24h) ─────
FEATURE_STATUS_PRECEDENCE = ["DEPLOY", "DECISION", "INCIDENT", "BLOCKER", "URGENT", "APPROVAL", "DIRECTION", "INFO"]

FEATURE_STATUS_VALUES = ["deployed", "decided", "incident", "blocked", "at_risk", "in_progress", "planned", "done", "unknown"]

SIGNAL_TO_FEATURE_STATUS = {
    "DEPLOY":   "deployed",
    "DECISION": "decided",
    "INCIDENT": "incident",
    "BLOCKER":  "blocked",
    "URGENT":   "at_risk",
    "APPROVAL": "decided",
    "DIRECTION": "in_progress",
    "INFO":     None,        # INFO never changes feature status — evidence only
}

# ── Auto-supersede policy (confirmed by Nghiem 2026-06-11) ───────────────────
FEATURE_AUTOSUPERSEDE = {
    "enabled": True,
    "high_confidence_requires": [
        "signal type in ('DEPLOY','DECISION')",
        "actor in PRIORITY_STAKEHOLDERS OR source = EMAIL from heineken.com domain",
        "confidence = 'high' per assign_confidence()",
    ],
    "on_high_confidence": "linked open actions for the feature_key → status='done', raw_json.superseded_by=<feature_key>, raw_json.superseded_reason=<signal summary>, raw_json.superseded_at=<ts>",
    "on_lower_confidence": "tag feature row conflicts[] += signal; surface as 'status_conflict' in briefing — NO auto-change",
    "never": [
        "never write status back to ClickUp or ADO — Supabase-only marking",
        "never supersede actions owned by Nghiem with draft_reply pending",
        "never supersede GOVERNANCE_REVIEW register actions",
    ],
}
```

---



## 18. AUTONOMOUS SCHEDULE (v1.10 — read by omni-orchestrator)

**Purpose:** The declarative schedule the agent brain (`omni-orchestrator`) reads each tick to
decide what is due. State + idempotency live in the Supabase `agent_runs` table (DDL applied
2026-06-23). The orchestrator NEVER self-fires — a tick arrives from an external scheduler
(Cowork / Claude Code cron) or a manual `run operator`. This config says only *what* runs *when*,
never *that* a run happens.

```python
SCHEDULE_TZ = "Asia/Bangkok"   # GMT+7 — every window below is local wall-clock

# Intraday auto-trigger tuning (v1.14). The intraday job fires on every OMNI-Pulse cron tick
# inside its window; cadence = how often that external routine ticks (recommended: hourly).
INTRADAY_SYNC_GATE_H = 3       # intraday LIGHTWEIGHT sync only actually fetches if cache older than this;
                               # otherwise the step logs skip(reason='cache_fresh') and only pulse runs.
                               # Keeps ClickUp-comment / Outlook calls gentle under an hourly tick.
INTRADAY_WINDOW = ("08:00", "18:30")   # business-hours envelope for the intraday job

# Each job = a time window + an ordered list of steps. The orchestrator runs the steps in
# order, skipping any once-per-day/week step already logged 'done' in agent_runs today/this week.
SCHEDULE = [
    {
        "job": "morning",
        "window": ("08:30", "11:00"),
        "weekday": None,                       # any day
        "steps": [
            {"run_kind": "sync",             "skill": "omni-data-sync",     "mode": "FULL",
             "once_per_day": True,  "staleness_gate_h": 2},
            {"run_kind": "briefing_morning", "skill": "omni-daily-briefing","mode": None,
             "once_per_day": True,  "staleness_gate_h": None},
        ],
    },
    {
        "job": "evening",
        "window": ("17:00", "20:00"),
        "weekday": None,
        "steps": [
            {"run_kind": "sync",             "skill": "omni-data-sync",     "mode": "LIGHTWEIGHT",
             "once_per_day": False, "staleness_gate_h": 2},
            {"run_kind": "eod",              "skill": "omni-eod-review",    "mode": None,
             "once_per_day": True,  "staleness_gate_h": None},
            {"run_kind": "briefing_evening", "skill": "omni-daily-briefing","mode": None,
             "once_per_day": True,  "staleness_gate_h": None},
        ],
    },
    {
        "job": "weekly_learning",
        "window": ("09:00", "12:00"),
        "weekday": "MO",                       # Mondays only
        "steps": [
            {"run_kind": "learning", "skill": "omni-operator-learning", "mode": None,
             "once_per_week": True, "staleness_gate_h": None},
        ],
    },
    {
        # v1.14 — intraday "always-on" job. Runs on EVERY tick inside its window (cadence set by the
        # external OMNI-Pulse hourly routine), NOT once_per_day. Two steps:
        #   1) sync_intraday — LIGHTWEIGHT, staleness-gated: fetches ONLY if cache > INTRADAY_SYNC_GATE_H,
        #      else skip(cache_fresh). This is what makes pulse event-AWARE (catches a P0/email/comment
        #      that landed since morning) without hammering ClickUp/Outlook every hour.
        #   2) pulse — read-only ~150-word "what to focus on RIGHT NOW" (omni-pulse). No writes, no API
        #      mutation. Surfaces new P0/P1, governance signals, and reply count.
        # compute_plan already handles this with NO orchestrator code change: neither step is
        # once_per_day, so both stay eligible on each in-window tick; the gate suppresses redundant syncs.
        "job": "intraday",
        "window": INTRADAY_WINDOW,             # ("08:00","18:30")
        "weekday": None,                       # any day (set ["MO".."FR"] at the routine if weekdays-only)
        "steps": [
            {"run_kind": "sync_intraday", "skill": "omni-data-sync", "mode": "LIGHTWEIGHT",
             "once_per_day": False, "staleness_gate_h": INTRADAY_SYNC_GATE_H},
            {"run_kind": "pulse",         "skill": "omni-pulse",      "mode": None,
             "once_per_day": False, "staleness_gate_h": None},
        ],
    },
]

# Cheap surface-only checks run on EVERY tick, regardless of window (no side effects, no auto-act):
SCHEDULE_TICK_CHECKS = {
    "reply_surface": "context_pack.clickup_replies_needed > 0 → surface count (NEVER auto-reply)",
    "drift_surface": "any on-disk skill version ≠ EXPECTED_SKILL_VERSIONS (§10) → surface (NEVER auto-fix)",
    "degraded_warn": "cache_check() degraded → warn + recommend manual sync (NEVER silent-proceed)",
    "next_due":      "report next_due_at across all jobs so a human knows when the agent next acts",
    "intraday_note": "the intraday job's pulse runs every in-window tick; its surface output IS the "
                     "intraday focus check — keep the orchestrator header ≤6 lines and let pulse print below",
}

# Orchestration safety contract (NON-NEGOTIABLE):
SCHEDULE_RULES = {
    "idempotency":    "before a once_per_day step: SELECT 1 FROM agent_runs WHERE run_date=CURRENT_DATE "
                      "AND run_kind=<kind> AND status='done' → if exists, log 'skipped' and move on. "
                      "once_per_week compares date_trunc('week', run_date) to date_trunc('week', CURRENT_DATE).",
    "staleness_gate": "a step with staleness_gate_h runs only if sync_runs freshness > gate hours; "
                      "if cache is fresher, skip the fetch (status='skipped', reason='cache_fresh').",
    "ledger":         "every step writes one agent_runs row: 'started' on entry, then 'done'/'failed'/'skipped'. "
                      "compute next_due_at = next window-start for the job and write it on the row.",
    "fail_open":      "a 'failed' step does NOT block later steps, EXCEPT a briefing/EOD whose only fresh "
                      "context depends on a sync that failed while cache is degraded → then surface degraded.",
    "governance":     "the orchestrator NEVER sends external comms and NEVER commits scope/capacity/SOW. "
                      "draft-email output and GOVERNANCE_REVIEW items stay human-gated (VN-GOV: YiLun→Andrea, "
                      "Peter CC). Autonomy is read / prepare / learn — never external commitment.",
    "manual_override":"`run operator` (manual trigger) runs the current window's due steps immediately, "
                      "ignoring wall-clock window but still honoring idempotency + staleness gates.",
    "intraday":       "the intraday job is NOT once_per_day — it runs on every in-window tick; the "
                      "INTRADAY_SYNC_GATE_H gate is what prevents redundant fetches under an hourly cron.",
    "event_trigger":  "trigger='event' (Stage 2, omni-orchestrator v1.1+) does NOT consult the time "
                      "windows — it runs the matching EVENT_TICKS fast-path immediately, then STOPS. "
                      "It inherits every governance guard below: draft/surface only, never send/commit.",
}

# ─────────────────────────────────────────────────────────────────────────────────────────────
# EVENT-DRIVEN REACTION CONTRACT (v1.14 — declarative spec; IMPLEMENTED by omni-orchestrator v1.1, Stage 2)
# ─────────────────────────────────────────────────────────────────────────────────────────────
# The clock-based SCHEDULE makes the operator *periodic*. EVENT_TICKS makes it *reactive*: an
# external webhook/poller fires `run operator` with trigger='event' and an `event` payload
# {type, ref, source}. The orchestrator matches event.type here and runs `fast_path` in order,
# writing one agent_runs row (run_kind='event:<type>') — then STOPS (no schedule sweep on an event tick).
#
# ⛔ AUTONOMY IS UNCHANGED. Every fast_path is read / prepare / DRAFT / surface only. An event tick
#    may pre-draft a reply via draft-email-skill and surface it, but a HUMAN still sends. No event
#    type may send external comms, confirm a GOVERNANCE_REVIEW item, or commit scope/capacity/SOW.
#    Governance events route to VN-GOV (Ha Hoang → YiLun → Andrea, Peter CC) — surfaced, never auto-acted.
#
# `detect` describes where the firing signal comes from (the external runner is responsible for the
# webhook/poll; until Stage-2 webhooks exist, the intraday job's gated sync+pulse already catches the
# same signals on the next hourly tick — EVENT_TICKS just makes the reaction immediate instead of ≤1h).
EVENT_TICKS = {
    "p0_incident": {
        "detect":     "source_items arrives is_urgent=true OR tag/keyword in {incident,blocker,prod-down,"
                      "outage,p1,regression,rollback} (same heuristic as omni-operator-learning STEP 1C.1)",
        "fast_path":  ["omni-data-sync(LIGHTWEIGHT, ungated)", "omni-pulse"],
        "surface":    "headline the incident + owner + nearest related risk; if a prior risk flagged it, "
                      "note lead-time (feeds recall). Create/raise a P0 action — internal only.",
        "autonomy":   "draft/surface only; NEVER auto-message the client or commit a fix ETA.",
    },
    "client_email": {
        "detect":     "new inbound source_type='email' from a client-side stakeholder (HEINEKEN_STAKEHOLDERS) "
                      "with a direct question or same-day ask",
        "fast_path":  ["omni-email-extractor(single thread)", "draft-email-skill(reply DRAFT)"],
        "surface":    "show the extracted ask + a ready reply draft in Nghiem's style (Hi @Name / Regards, "
                      "Nghiem). Queue a reply-required action.",
        "autonomy":   "DRAFT ONLY — the draft is surfaced for human send. Never auto-send. "
                      "If the ask touches capacity/SOW/scope → route to VN-GOV, do NOT draft a direct reply to Andrea.",
    },
    "governance_comment": {
        "detect":     "ClickUp comment OR Teams message mentioning capacity / FTE / SOW / scope / cost / "
                      "rate basis, OR authored by Andrea/YiLun on a governance thread",
        "fast_path":  ["omni-data-sync(LIGHTWEIGHT, ungated, comments on)", "omni-pulse"],
        "surface":    "flag as GOVERNANCE_REVIEW, route per VN-GOV (Delivery → Ha Hoang → YiLun → Andrea, "
                      "Peter CC). Surface a prepared internal summary for Nghiem — NEVER a client-facing draft.",
        "autonomy":   "⛔ HARD STOP on external action. Constitution-level. Surface + route only.",
    },
    "ado_build_break": {
        "detect":     "ado_work_item / pipeline signal indicating a failed build or broken main on Heineken\\OMS",
        "fast_path":  ["ado-oms-knowledge-sync(incremental)", "omni-pulse"],
        "surface":    "name the failing item + likely owner from recent ADO activity; raise an internal P1 action.",
        "autonomy":   "surface only; never push code, never edit the pipeline.",
    },
}
EVENT_TICK_RULES = {
    "single_shot":   "an event tick runs ONLY its fast_path then stops — it never sweeps the time SCHEDULE.",
    "idempotency":   "dedupe on (event.type, event.ref): if an agent_runs row for this ref exists today, "
                     "log skip(reason='event_seen') — a webhook retry must not double-draft.",
    "ledger":        "one agent_runs row run_kind='event:<type>', trigger='event', raw_json={ref,source}.",
    "governance":    "the §18 SCHEDULE_RULES['governance'] guard applies in full to every event fast_path.",
    "fallback":      "no webhook infra yet → the intraday job already catches these signals within ≤1 cron "
                     "interval; EVENT_TICKS only upgrades latency from ~hourly to immediate once Stage 2 ships.",
}
```

**`agent_runs` table contract** (Supabase, RLS off — created 2026-06-23):
`id` uuid · `run_date` date (GMT+7) · `run_kind` text (free, no CHECK) · `mode` text ·
`status` ∈ {started,done,failed,skipped} · `trigger` ∈ {cron,manual,chained} ·
`started_at` · `finished_at` · `next_due_at` · `summary` · `raw_json`.
Written by `omni-orchestrator`; read by briefing/EOD only for "did the agent already run me today"
awareness. Structurally separate from `actions` so autonomy telemetry never enters the work backlog
or the self-improve STEP 2B auto-age pass.

---

## 19. SKILL PATCH AUTO-MERGE POLICY (v1.13 — read by omni-operator-learning v1.3+)

**Purpose:** Turn the human-gated patch-export flow into a git-native auto-PR loop WITHOUT
letting the agent rewrite its own governing code unsupervised. Claude Code routines push ONLY
to `claude/`-prefixed branches (branch safety ON), so every structural change becomes a PR.
This policy decides which PRs may **auto-merge** (Tier 1) vs require a **human merge** (Tier 2).
Behavioral `operator_rule`s are Tier 0 and never touch git at all.

```python
PATCH_REPO = {
    "base_branch":         "main",
    "patch_branch_prefix": "claude/skill-patch-",   # branch safety MUST stay ON (default)
    "skills_path":         "skills/",            # path within the repo to the skill suite
    "required_check":      "omni-skill-eval",        # GitHub Action status check (build step 3)
    "pr_labels":           {"auto": "automerge:eligible", "human": "needs-human"},
}

# Tier eligibility — evaluated by omni-operator-learning STEP 3 when drafting a patch.
PATCH_TIERS = {
    "tier0_behavioral": "operator_rule promotion — NO git; auto-applied at briefing/EOD STEP 0A2 (live).",
    "tier1_auto": {            # → label automerge:eligible; merges automatically once required_check green
        "applies_to":        "ONE non-protected skill, touching ONLY the flagged target_step",
        "max_changed_lines": 40,                    # diff larger than this → escalate to Tier 2
        "max_files":         1,
        "requires":          "rule.occurrences >= 3 AND clear target_skill+target_step AND eval green",
        "auto_merge":        True,
    },
    "tier2_human": {           # → label needs-human; PR only, NEVER auto-merge
        "applies_to":        "omni-utils, omni-config, omni-orchestrator, any PROTECTED_PATCH_FILES, "
                             "multi-file, or diff beyond tier1 caps",
        "auto_merge":        False,
    },
}

# Files/skills that can NEVER auto-merge regardless of tier (constitution-level).
PROTECTED_PATCH_FILES = [
    "skills/omni-config/**",
    "skills/omni-utils/**",
    "skills/omni-orchestrator/**",   # the agent brain is edited only via human merge
    "**/*governance*", "**/*VN-GOV*",
    ".github/workflows/**",               # the eval gate cannot rewrite itself
]
# Any patch whose CONTENT touches governance routing, the autonomy boundary, or a guardrail block
# → forced Tier 2 even on an otherwise-eligible file.
PROTECTED_PATCH_CONTENT = ["yilun", "andrea", "vn-gov", "capacity", "sow", "scope governance",
                           "autonomy boundary", "governance guard", "branch safety"]

PATCH_AUTOMERGE_POLICY = {
    "weekly_automerge_cap": 3,        # ≤3 Tier-1 auto-merges per learning run (matches STEP 3 patch cap)
    "eval_gate":            "auto-merge fires ONLY when required_check='omni-skill-eval' = success. "
                            "No check / failed / pending → PR stays open for human review.",
    "circuit_breaker":      "if calibration eval-score trend = 'degrading' for 2 consecutive weekly "
                            "runs → set AUTOMERGE_ENABLED=False, relabel all open Tier-1 PRs needs-human, "
                            "surface for human re-enable. Self-protects against a bad learning spiral.",
    "rollback":             "every auto-merge is a single revertable commit; the agent_runs/actions "
                            "audit links operator_rule → PR url → merge sha. Undo = git revert <sha>.",
    "audit":                "STEP 5 LEARNING_RUN logs {rule_key, pr_url, tier, merged: bool} per patch.",
}
AUTOMERGE_ENABLED = True   # master switch; circuit breaker or a human may set False

# HARD GUARDRAILS (NON-NEGOTIABLE):
#  - NEVER push to base_branch directly — branch safety stays ON; all changes via claude/ PRs.
#  - NEVER auto-merge Tier 2 / PROTECTED_PATCH_FILES / PROTECTED_PATCH_CONTENT — human merge only.
#  - NEVER auto-merge without a green required_check.
#  - NEVER weaken governance / autonomy-boundary / guardrail blocks via an auto-merged patch.
#  - Learning loop OPENS & LABELS PRs; the merge of a Tier-1 PR is the GitHub Action's auto-merge
#    on green — never an interactive Claude send and never a direct write to main.
```

**Why the line is drawn here:** Tier 1 delivers the "feels fully automatic" experience for the
safe majority of fixes (a small, evidenced, single-step change that passes its own eval). Tier 2
keeps a human merge on the brain-surgery class — the agent's own brain (`omni-orchestrator`),
shared infra (`omni-utils`/`omni-config`), and anything governance-touching — preserving the
constitution (VN-GOV: YiLun→Andrea, Peter CC) that the rest of the architecture depends on.

---

- This file is READ-ONLY — never execute directly
- Never hardcode any of these values in consumer skill files
- When a value changes (e.g. new OPCO, new Teams chat) → edit here only
- All consumer skills read this at STEP 0 before reading omni-utils
- **NormalizedSignal is the output contract** for email extractor, Teams extraction, ClickUp extraction, and EOD review
- **FEATURE_REGISTRY_SEED is bootstrap-only** — after first load, Supabase `feature_status` table is authoritative; edit aliases/features there, not here
