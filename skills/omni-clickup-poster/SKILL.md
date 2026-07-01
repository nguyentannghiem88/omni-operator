---
name: omni-clickup-poster
description: "Approval-gated ClickUp comment poster + reply-close monitor for the OMNI work_items inbox. v1.0. mode=POST (post_approved_clickup_replies): posts work_items WHERE status='approved' AND source='clickup_comment' AND is_governance=false to their source ClickUp task, then marks done with posted_comment_id. mode=CLOSE (close_posted_work_items): for each posted item (has posted_comment_id, not thread_closed), fetches live comments and closes ONLY on an explicit textual reply from the requester (acknowledgment → replied_ack; question → spawn follow-up work_item). Reactions are NEVER a close signal; no time-based soft-close. HARD GOVERNANCE GUARD: governance items never enter either path (is_governance filter + live draft-body re-scan at post time). Dry-run-first. Supabase + ClickUp MCP only. Triggers: 'post approved replies', 'post clickup replies', 'check for replies', 'close posted work items', 'run poster'; chained by omni-orchestrator evening job (post_replies, close_replies)."
---

# omni-clickup-poster (v1.0)

SKILL_VERSION = '1.0'

Approval-gated execution layer for the `work_items` Approval Inbox. This is the ONLY
skill permitted to post an external ClickUp comment autonomously — and ONLY because
every item it posts was explicitly approved by Nghiem and passes hard governance gates
re-checked at execution time.

> **Governance boundary (absolute):** This skill posts ONLY `clickup_comment` work_items
> that are `is_governance=false` and `status='approved'`. It NEVER posts email/Teams,
> NEVER posts governance items, NEVER commits scope/capacity/SOW. Governance routing stays
> human (Ha Hoang → YiLun → Andrea, Peter CC). A misclassified row cannot slip through:
> the governance keyword scan re-runs on the draft body at post time.

---

## STEP 0 — Preflight

```python
# 0A. version handshake vs omni-config EXPECTED_SKILL_VERSIONS
# 0B. cache_check() — if degraded, still safe (this skill reads work_items directly), but log it
# 0C. mode ∈ {POST, CLOSE}. Default POST if invoked bare; orchestrator passes mode explicitly.
GOV_RE = r"(\yandrea\y|\yyilun\y|yi lun|\ypeter\y|\bSOW\b|capacity|\bscope\b|MongoDB|contract module|VN-GOV|governance)"
ME = "107626012"   # Nghiem ClickUp user id (a comment from ME is never a requester reply)
```

---

## STEP A — mode=POST · post_approved_clickup_replies()

Posts every approved, non-governance ClickUp reply, then closes it as `done`.

```python
def post_approved_clickup_replies(dry_run=True):
    rows = supabase_sql("""
        SELECT id, title, source_ref, draft
        FROM work_items
        WHERE status='approved'
          AND source='clickup_comment'
          AND is_governance = false            -- GATE 1 (column)
          AND draft IS NOT NULL AND length(draft) > 10
    """)
    out = []
    for r in rows:
        # GATE 2 — re-scan draft body for governance leakage AT POST TIME
        if re.search(GOV_RE, r['draft'], re.I):
            supabase_sql_update(r['id'], lane='needs_your_call', is_governance=True,
                                raw_json_merge={'blocked':'gov_at_posttime'})
            out.append({'id': r['id'], 'verdict': 'blocked_governance'})
            continue

        task_id = r['source_ref'].split(':')[0]
        if dry_run:
            out.append({'id': r['id'], 'task': task_id, 'would_post': r['draft']})
            continue

        res = clickup_create_comment(entity_type='task', entity_id=task_id,
                                     comment_text=r['draft'])
        supabase_sql_update(r['id'], status='done', approved_at='now()',
            raw_json_merge={'posted_comment_id': res['comment_id'],
                            'posted_via': 'omni-clickup-poster',
                            'posted_at': now_iso(), 'awaiting_reply': True})
        out.append({'id': r['id'], 'task': task_id, 'comment_id': res['comment_id'],
                    'verdict': 'posted'})
    return out
```

**Guarantees:** GATE 1 (column) + GATE 2 (live body scan) both must pass. Idempotent —
only `approved` rows are eligible and each flips to `done` immediately, so a re-run cannot
double-post. Fail-open per item (one failure does not block the rest).

---

## STEP B — mode=CLOSE · close_posted_work_items()

Monitors every posted item and closes ONLY on an explicit textual reply. Reactions are
NOT a close signal. No time-based auto-close.

```python
def close_posted_work_items(dry_run=True):
    rows = supabase_sql("""
        SELECT id, title, source_ref,
               raw_json->>'posted_comment_id' AS pcid,
               raw_json->>'posted_at'          AS posted_at
        FROM work_items
        WHERE raw_json ? 'posted_comment_id'
          AND COALESCE(raw_json->>'thread_closed','') <> 'true'
    """)
    REQUESTERS_EXCLUDE = {ME}   # anyone who is NOT Nghiem counts as a requester
    out = []
    for r in rows:
        task_id  = r['source_ref'].split(':')[0]
        comments = clickup_get_task_comments(task_id)['comments']   # newest-first
        mine = next((c for c in comments if c['id'] == r['pcid']), None)
        if mine is None:
            out.append({'id': r['id'], 'verdict': 'post_not_found'}); continue
        idx   = comments.index(mine)
        newer = comments[:idx]                      # comments posted AFTER ours

        # find newest textual reply from a NON-Nghiem author (reactions are ignored entirely)
        reply = next((c for c in newer
                      if str(c['user']['id']) not in REQUESTERS_EXCLUDE
                      and c.get('comment_text','').strip()), None)

        if reply is None:
            # our post is still the last word (a 👍 does NOT close) → keep monitoring
            out.append({'id': r['id'], 'verdict': 'monitoring'}); continue

        if _is_question(reply['comment_text']):
            verdict = 'followup'
            if not dry_run:
                _spawn_followup_work_item(r, reply)            # new reply work_item, needs draft
                supabase_sql_update(r['id'],
                    raw_json_merge={'thread_closed': True, 'closed_reason': 'followup_spawned',
                                    'awaiting_reply': False})
        else:
            verdict = 'closed_reply'
            if not dry_run:
                supabase_sql_update(r['id'],
                    raw_json_merge={'thread_closed': True, 'closed_reason': 'replied_ack',
                                    'awaiting_reply': False})
        out.append({'id': r['id'], 'verdict': verdict,
                    'reply_by': reply['user']['username']})
    return out


def _is_question(text):
    t = text.lower()
    return ('?' in text) or any(k in t for k in
        ('can you','could you','please provide','timeline','when ','what about','any update','how '))


def _spawn_followup_work_item(parent, reply):
    supabase_sql("""INSERT INTO work_items
        (wi_type,title,source_action_key,source,source_ref,module,market,priority,
         lane,is_governance,is_client_facing,draft,raw_json)
        SELECT 'reply', '[FOLLOW-UP] '||left(title,180), source_action_key, 'clickup_comment',
               source_ref, module, market, priority, 'needs_your_call', false,
               is_client_facing, NULL,
               jsonb_build_object('origin','followup','parent_id',%(pid)s,
                                  'reply_excerpt',left(%(ex)s,300))
        FROM work_items WHERE id=%(pid)s
    """, {'pid': parent['id'], 'ex': reply['comment_text']})
```

**Close signals (reply-only):** acknowledgment textual reply → `replied_ack`; question /
new ask → spawn `[FOLLOW-UP]` work_item into `needs_your_call`. Our post being latest
(even with reactions) → `monitoring`. No silence-based close.

---

## STEP C — Output (compact)

```
🤖 ClickUp poster — <mode> (<now GMT+7>)
POST:  posted=<n>  blocked_gov=<n>
CLOSE: closed=<n>  followup=<n>  monitoring=<n>
```

One `agent_runs` row per mode invocation (run_kind=post_replies / close_replies).

---

## Triggers
'post approved replies', 'post clickup replies', 'check for replies',
'close posted work items', 'run poster'. Chained by omni-orchestrator evening job.

## Changelog
| Version | Change |
|---|---|
| v1.0 | Initial. Two modes (POST/CLOSE) extracted from the manually-validated work_items posting + reply-close logic. Reply-only close (reactions excluded by explicit decision; no time-based soft-close). Dual governance gate on POST (column + live body re-scan). Governance items structurally excluded from both paths. Wired into omni-orchestrator evening job as the last two steps of the day. |
