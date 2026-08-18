---
name: project_coding_backups
description: How the analyzer protects the researcher's coding labels (external JSON backups + restore)
metadata:
  type: project
---

The researcher's coding (change-tags, notes, pauses, video-alignment, origin
classifications) is the irreplaceable output — loaded session copies are
re-creatable from the study export, so backups exclude them. `app/analysis/backup.py`:

- **External file backups, not in-DB snapshots** (in-DB snapshots die with the
  file). JSON dumps written to `coding_backups/` beside `mopt_analysis.db`.
- **Auto-backup before destructive actions**: `auto_backup(adb, ids, reason)` is
  called at the top of `reset-tags`, `delete-session`, and `bulk-delete` (never
  raises — a backup failure must not block the action).
- **Manual**: `GET /analysis/coding-backup.json` downloads all coding (button
  "Back up labels"); `POST /analysis/coding-restore` restores from a backup body
  (button "Restore…"). Restore is **non-destructive** — matches sessions by
  `source_session_id`, skips exact-duplicate annotations (dedup key = type/
  row_ref/label/text/video_pos), fills video-meta only where missing.

See [[project_session_coding_scheme]] (the tags themselves) and the destructive
Reset-tags button this guards.
