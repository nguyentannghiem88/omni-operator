# OMNI AI Operator — Routine Setup (no coding needed)

This folder turns your OMNI operator into two automatic daily runs in the cloud, so it
works even when your laptop is closed. Total time: about 20–30 minutes, once.

You'll do four phases:
- **A.** Put this folder into a private GitHub repository.
- **B.** Add your ADO token as a secret and allow the ADO web address.
- **C.** Create two routines (morning + evening).
- **D.** Test once and check it worked.

You never touch a terminal. Just upload files and fill in forms.

---

## Phase A — Create the GitHub repository

1. Go to **https://github.com/new**
2. **Repository name:** `omni-operator`
3. Choose **Private** (important — keep it private).
4. Leave everything else as-is. Click **Create repository**.
5. On the next page, click the link **“uploading an existing file”** (or **Add file → Upload files**).
6. Open this `omni-operator` folder on your computer, select **everything inside it**
   (the `skills` folder, `CLAUDE.md`, `setup.sh`, `README.md`, `.gitignore`, `.env.example`),
   and **drag them into the upload area**. Wait for the file list to finish loading
   (you should see the `skills` folder and the files).
7. Click **Commit changes**.

✅ Done when your repo shows the `skills` folder plus `CLAUDE.md` and `setup.sh`.

> Tip: if dragging the folder doesn't keep the structure in your browser, install the free
> **GitHub Desktop** app, drag the files in there, and click **Commit** → **Push**. Same result.

---

## Phase B — Add the ADO secret and allow the ADO address

This is set on the routine's **environment** (you'll do it while creating the first routine
in Phase C — Step 5). Here's what to enter when you get there:

- **Environment variable (secret):**
  - Name: `ADO_PAT`
  - Value: *your Azure DevOps Personal Access Token* (the same token from your old `ado_pat.txt`)
- **Network access:** set to **Custom**, and add this allowed domain:
  - `dev.azure.com`
  - Keep **“include default list of common package managers”** checked.

Your ClickUp, Microsoft 365, and Supabase connectors do **not** need any domains added —
they go through Anthropic automatically.

---

## Phase C — Create the two routines

Open **https://claude.ai/code/routines** and click **New routine**. Do this **twice** —
once for morning, once for evening. Everything is identical except the name and time.

For each routine, fill in:

1. **Name:**
   - First routine: `OMNI-Morning`
   - Second routine: `OMNI-Evening`

2. **Prompt / Instructions:** paste this exact text (same for both):

```
First, run: bash setup.sh
Then read /mnt/skills/user/omni-orchestrator/SKILL.md and execute it as a scheduled
tick with trigger="cron":
- PERCEIVE: cache_check() + the agent_runs ledger + the current GMT+7 time.
- DECIDE what is due per omni-config section 18 SCHEDULE (idempotency, staleness gate,
  time window). Morning: FULL data sync then the daily briefing. Evening: LIGHTWEIGHT
  data sync, then the EOD review, then the evening briefing. On Mondays also run the
  weekly operator-learning.
- ACT: chain only the steps that are due, writing one agent_runs row per step.
Honor the governance guard: never send external emails or Teams messages, and never
commit scope, capacity, or SOW. If nothing is due, print the idle line and stop.
Keep the summary compact.
```

3. **Repository:** select your `omni-operator` repo.

4. **Environment:** use **Default**, then open its settings and apply the **Phase B** items
   (add the `ADO_PAT` secret, set Network access to Custom + `dev.azure.com`). You only need
   to do this once; the second routine can reuse the same environment.

5. **Trigger → Schedule:**
   - `OMNI-Morning`: **Daily**, time **09:00**, timezone **GMT+7 (Asia/Ho_Chi_Minh)**
   - `OMNI-Evening`: **Daily**, time **18:00**, timezone **GMT+7 (Asia/Ho_Chi_Minh)**

6. **Connectors:** leave ClickUp, Microsoft 365, and Supabase included. Remove others you
   don't need.

7. Click **Create**.

> The Monday weekly-learning run happens automatically inside the 09:00 OMNI-Morning run —
> you do **not** need a separate routine for it.

---

## Phase D — Test it once

1. Open **OMNI-Morning**, click **Run now**.
2. Wait for the run to finish, then **click the run to open the transcript**.
3. A green status only means it *started* cleanly — read the transcript to confirm it
   actually synced and produced a briefing.

**What a good run looks like:** it runs `setup.sh`, reads the orchestrator, decides what's
due, runs the data sync and briefing, and writes rows to the `agent_runs` table.

---

## If something looks wrong

Open the failed/odd run, copy the last part of the transcript, and send it to me in chat.
The usual first-run fixes are tiny:
- **“host_not_allowed / 403 dev.azure.com”** → the network allowlist in Phase B wasn't saved.
- **“ADO_PAT not set”** → the secret name/value in Phase B needs fixing.
- **“skills not found / no such file /mnt/skills/user/...”** → tell me; I'll adjust `setup.sh`
  to the path this environment actually uses (this is the one thing that can vary).

That's the whole setup. After Phase D passes, you do nothing — it runs every day at 09:00
and 18:00 GMT+7, catches Mondays' learning automatically, and self-heals a missed day the
next time you type **"run operator"** by hand.
