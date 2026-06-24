---
name: project-knowledge-sync
version: "2.0"
description: "Indexes OMNI project reference files (PDFs in /mnt/project/) into Supabase project_context. v2.0: Supabase-only — Mem0 retired. Uses MD5 hash-checking for change detection. Triggered during omni-data-sync FULL runs or manually via: 'sync project files', 'index project docs', 'refresh project knowledge'. Reads: project_context (file hash index). Writes: project_context (upsert_project_context()). Triggers on any question about OMNI/REP/LOOP/HAP architecture when project_context is empty."
---

# Project Knowledge Sync

Indexes all project reference files from `/mnt/project/` into Supabase `project_context` (v2.0 — Mem0 retired).
Each file is vision-analyzed (slides as images), summarized, and stored as a structured
Supabase project_context row. Hash-based change detection ensures only changed/new files are re-indexed.

---

## FILE FORMAT DISCOVERY

**⚠️ CRITICAL**: Files in `/mnt/project/` have `.pdf` extension but are actually **ZIP archives
containing JPEG slide images** (1.jpeg, 2.jpeg, … N.jpeg). They are NOT text-extractable PDFs.

Reading strategy: extract images → read each with vision → summarize per slide → aggregate.

---

## STEP 0 — LOAD EXISTING INDEX (Supabase)

The `project_context` table IS the index — no separate index entry exists.

```sql
SELECT file_stem, file_hash, indexed_at, slide_count, module FROM project_context;
```

Build `index = {file_stem: {hash, indexed_at, slides, module}}` from the rows.
If table is empty → treat all files as new.

---

## STEP 1 — SCAN PROJECT FILES

```python
import os, hashlib, zipfile

PROJECT_DIR = "/mnt/project/"
files = sorted([f for f in os.listdir(PROJECT_DIR) if not f.startswith('.')])

file_info = {}
for filename in files:
    path = os.path.join(PROJECT_DIR, filename)
    size = os.path.getsize(path)
    with open(path, 'rb') as fh:
        md5 = hashlib.md5(fh.read()).hexdigest()
    
    # Detect slide count (ZIP of JPEGs)
    slide_count = 0
    try:
        with zipfile.ZipFile(path) as z:
            slide_count = len([n for n in z.namelist() if n.endswith(('.jpeg', '.jpg', '.png'))])
    except Exception:
        pass
    
    file_info[filename] = {"hash": md5, "size": size, "slides": slide_count}
```

---

## STEP 2 — DIFF AGAINST INDEX

For each file in `file_info`:
- **Hash unchanged** AND `indexed_at` exists in INDEX → **SKIP** (log: `[SKIP] {filename} — unchanged`)
- **Hash changed** OR **not in INDEX** → **QUEUE for indexing** (log: `[QUEUE] {filename} — new/changed`)

If queue is empty → log "All project files up to date" → skip to STEP 5.

---

## STEP 3 — INDEX EACH QUEUED FILE

For each file in queue:

### 3A — Extract slides

```python
import zipfile, os, base64

def extract_slides(path, tmpdir="/tmp/proj_slides"):
    os.makedirs(tmpdir, exist_ok=True)
    # Clear previous
    for f in os.listdir(tmpdir):
        os.remove(os.path.join(tmpdir, f))
    
    with zipfile.ZipFile(path) as z:
        imgs = sorted([n for n in z.namelist() if n.endswith(('.jpeg', '.jpg', '.png'))])
        extracted = []
        for img_name in imgs:
            out_path = os.path.join(tmpdir, img_name)
            with z.open(img_name) as src, open(out_path, 'wb') as dst:
                dst.write(src.read())
            extracted.append(out_path)
    return extracted
```

### 3B — Vision analysis per slide

**Token budget**: Large decks (>30 slides) are expensive. Use tiered strategy:
- **≤15 slides**: Read ALL slides individually
- **16–40 slides**: Read slides 1–5 fully, then sample every 3rd slide
- **>40 slides**: Read slides 1–5, sample every 5th, read last 3

For each slide to read:
- Use `view` tool on the image path
- Extract: title, key concepts, data points, module names, flow descriptions

### 3C — Aggregate into structured summary

After reading slides, produce this structure:

```python
doc_summary = {
    "filename": filename,
    "doc_type": "<infer: HighLevel/Architecture/Toolkit/Intro/etc>",
    "module": "<infer: OMNI/REP/HAP/LOOP/PEM/multi>",
    "total_slides": N,
    "slides_read": M,
    "key_topics": ["topic1", "topic2", ...],  # max 10
    "module_coverage": ["OMNI", "REP", ...],  # which modules mentioned
    "opco_coverage": ["MY", "ID", ...],       # which OPCOs mentioned
    "architecture_notes": "...",              # max 200 words, architecture decisions
    "feature_highlights": ["...", "..."],     # max 8 bullet points
    "glossary": {"term": "definition"},       # key terms defined in doc, max 10
    "slide_index": [                          # one line per slide read
        {"slide": 1, "title": "...", "summary": "..."},
        ...
    ]
}
```

### 3D — Write to Supabase

```python
upsert_project_context(
    file_stem   = filename.rsplit(".", 1)[0],   # e.g. "OMNIHighLevel"
    file_path   = path,
    file_hash   = file_info[filename]["hash"],
    module      = doc_summary["module"],
    slide_count = doc_summary["total_slides"],
    content     = doc_summary,                  # full JSON from 3C
)
```

- Conflict key: `file_stem` — re-indexing a changed file UPDATEs the same row.
- One row per file, always.

**File → Tag mapping:**

| Filename | Tag stem | Module |
|---|---|---|
| OMNIHighLevel.pdf | OMNI-HighLevel | OMNI |
| OMNIfunctionalarchitectureL13.pdf | OMNI-FuncArch | OMNI |
| PPT_REP_Asset_management_Toolkit.pdf | REP-AssetMgmt | REP |
| PPT_REP_Intro_Master_Deck_v2.pdf | REP-Intro | REP |
| REPCustomer360Toolkit.pdf | REP-Customer360 | REP |
| REPExecution360Toolkit.pdf | REP-Execution360 | REP |

---

## STEP 4 — UPDATE INDEX

**SKIPPED by design** — `project_context` is the index. Hash comparison in STEP 2
reads directly from the table; the STEP 3D upsert updates `file_hash` + `indexed_at`.
No separate index record exists anywhere.

---

## STEP 5 — DELIVER SUMMARY

Output to chat:
```
PROJECT KNOWLEDGE SYNC — <datetime GMT+7>

Files scanned: X
  ✅ Indexed (new/changed): <list>
  ⏭ Skipped (unchanged): <list>

Supabase project_context rows written: X
Index state: ✅ (X files tracked in project_context)

[Coverage]
  OMNI docs: X | REP docs: X
  Total slides analyzed: X
```

---

## RETRIEVAL GUIDE (for other skills)

When answering questions about project architecture/features:

1. Query Supabase: `SELECT * FROM project_context` (this IS the index)
2. Find relevant entry: check `module_coverage`, `key_topics` in index
3. Semantic search: query e.g. `"OMNI functional architecture"`, `"REP customer 360"`, `"asset management module"`
4. Parse JSON after `---JSON---` → use `feature_highlights`, `architecture_notes`, `slide_index`

**Query → likely doc mapping:**
- "OMNI architecture", "system design" → OMNI-FuncArch, OMNI-HighLevel
- "REP features", "route execution" → REP-Intro, REP-Execution360
- "customer 360", "outlet data" → REP-Customer360
- "asset tracking", "cooler management" → REP-AssetMgmt

---

## GUARDRAILS

- Never write more than one project_context row per file — upsert conflicts on `file_stem`
- Never skip the file_hash update in upsert — it's the source of truth for change detection
- If vision read fails for a slide → log it, continue with remaining slides
- Slide sampling (for large decks) must always include first 5 and last 3 slides
- ⛔ Zero Mem0 calls — Supabase `project_context` only
- Store verbatim JSON in `content` — no lossy re-extraction on write
- If ZIP extraction fails → log error, skip file, continue with others
- When called from `omni-data-sync`: run silently, append results to sync summary
