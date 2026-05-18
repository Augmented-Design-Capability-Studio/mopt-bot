"""Prune all sessions from the DB except a caller-supplied keep-set.

Use when the researcher UI's session list and the DB have drifted apart
(e.g. test-fixture pile-up, a partial bulk-delete failure left orphan rows,
manual cleanup wanted). Hard-deletes any session whose id isn't in the
keep-set; cascades through messages / runs / session_snapshots via the
existing ``ON DELETE CASCADE`` FKs.

### Getting the keep-set

The simplest source is the researcher UI itself — open the browser
console on the researcher page and run:

    copy(JSON.stringify(
      Array.from(document.querySelectorAll('.session-item input[type=checkbox]'))
        .map(el => el.value)
    ))

That copies the visible session-id list to your clipboard, paste it as
the script input.

### Usage

Dry-run (default — shows what *would* be deleted, doesn't touch the DB):

    cd backend
    python scripts/prune_sessions.py keep-ids.txt

where ``keep-ids.txt`` is a newline-separated list of session ids OR a
JSON array. Pass ``-`` to read from stdin instead:

    echo '["abc123…", "def456…"]' | python scripts/prune_sessions.py -

Apply the prune (writes a timestamped backup first):

    python scripts/prune_sessions.py keep-ids.txt --apply

Pass ``--keep-empty`` to also retain sessions with zero messages / runs /
snapshots (the "empty test fixture" class). Default is to prune them.

### Safety

- Default mode is dry-run. ``--apply`` is required to actually delete.
- A timestamped ``data/<db-name>.backup-YYYYMMDD-HHMMSS`` copy is
  written before any DELETE runs. Recover by replacing the live DB
  with the backup.
- Cascade is enforced via ``PRAGMA foreign_keys = ON`` per connection;
  children are removed atomically with their parent session.
- After the DELETE the script runs ``VACUUM`` so the file shrinks.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402


def _read_keep_ids(source: str) -> set[str]:
    """Parse keep-ids from a file path or '-' (stdin). Accepts a JSON
    array of strings OR a newline-separated list. Comments (#…) and
    blank lines are ignored.
    """
    if source == "-":
        raw = sys.stdin.read()
    else:
        raw = Path(source).read_text(encoding="utf-8")
    raw = raw.strip()
    if not raw:
        return set()
    # Try JSON first.
    if raw.startswith("["):
        try:
            arr = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"keep-ids file looks like JSON but failed to parse: {exc}")
        if not isinstance(arr, list) or not all(isinstance(x, str) for x in arr):
            raise SystemExit("keep-ids JSON must be a list of strings")
        return {x.strip() for x in arr if x.strip()}
    # Otherwise treat as newline-separated.
    ids: set[str] = set()
    for line in raw.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            ids.add(line)
    return ids


def _resolve_db_path() -> Path:
    """Resolve the SQLite DB path from the configured DATABASE_URL.

    Bail loudly on non-SQLite URLs so we don't accidentally drop
    production rows on a Postgres / MySQL deployment via this script —
    that variant would need a different driver path.
    """
    url = get_settings().database_url
    if not url.startswith("sqlite:///"):
        raise SystemExit(
            f"This script only supports SQLite databases; configured URL is {url!r}. "
            "For Postgres / other engines, use a deployment-side prune query instead."
        )
    rel = url[len("sqlite:///"):].lstrip("/")
    return Path(rel)


def _summary(conn: sqlite3.Connection, keep_ids: set[str], keep_empty: bool) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT id FROM sessions")
    db_ids = {r[0] for r in cur.fetchall()}
    missing_keepers = sorted(keep_ids - db_ids)
    keep_present = keep_ids & db_ids
    delete_candidates = db_ids - keep_ids
    if not keep_empty:
        # Empty-fixture sessions (no messages, runs, or snapshots) are pruned
        # regardless. Caller can opt out with --keep-empty.
        cur.execute(
            """
            SELECT id FROM sessions s
            WHERE NOT EXISTS (SELECT 1 FROM messages m WHERE m.session_id = s.id)
              AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.session_id = s.id)
              AND NOT EXISTS (SELECT 1 FROM session_snapshots sn WHERE sn.session_id = s.id)
            """
        )
        empty_ids = {r[0] for r in cur.fetchall()}
        # Empty sessions in the keep-set are still preserved — explicit keep wins.
        delete_candidates |= empty_ids - keep_ids
    cur.execute("SELECT COUNT(*) FROM messages")
    child_msgs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM runs")
    child_runs = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM session_snapshots")
    child_snaps = cur.fetchone()[0]
    return {
        "db_total": len(db_ids),
        "keep_in_db": len(keep_present),
        "keep_missing_from_db": missing_keepers,
        "to_delete": sorted(delete_candidates),
        "child_messages_total": child_msgs,
        "child_runs_total": child_runs,
        "child_snapshots_total": child_snaps,
    }


def _print_report(summary: dict, applied: bool) -> None:
    header = "PRUNED" if applied else "DRY-RUN"
    print(f"\n[{header}] session-prune summary")
    print(f"  sessions in DB before     : {summary['db_total']}")
    print(f"  keep-set size             : {summary['keep_in_db'] + len(summary['keep_missing_from_db'])}")
    print(f"  keepers present in DB     : {summary['keep_in_db']}")
    if summary["keep_missing_from_db"]:
        print(
            f"  keepers MISSING from DB   : {len(summary['keep_missing_from_db'])} "
            f"(first 5: {summary['keep_missing_from_db'][:5]})"
        )
    print(f"  to-delete count           : {len(summary['to_delete'])}")
    print(f"  child rows (msg/run/snap) : "
          f"{summary['child_messages_total']} / "
          f"{summary['child_runs_total']} / "
          f"{summary['child_snapshots_total']}")
    if not applied and summary["to_delete"]:
        sample = ", ".join(summary["to_delete"][:3])
        more = "" if len(summary["to_delete"]) <= 3 else f" (+{len(summary['to_delete']) - 3} more)"
        print(f"  sample ids to delete      : {sample}{more}")
        print("\n  Re-run with --apply to actually delete.")
    elif applied:
        print("  ✓ Delete + VACUUM completed.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "keep_source",
        help="Path to a file containing keep-ids (one per line OR a JSON array), or '-' for stdin.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete (default is dry-run).",
    )
    parser.add_argument(
        "--keep-empty",
        action="store_true",
        help="Preserve sessions with zero messages / runs / snapshots. Default is to prune them.",
    )
    args = parser.parse_args(argv)

    keep_ids = _read_keep_ids(args.keep_source)
    if not keep_ids:
        print("WARNING: keep-set is EMPTY — every session in the DB would be deleted.")
        if args.apply:
            confirm = input("Type 'wipe everything' to proceed: ").strip()
            if confirm != "wipe everything":
                print("Aborted.")
                return 1

    db_path = _resolve_db_path()
    if not db_path.exists():
        raise SystemExit(f"DB file not found at {db_path}")

    if args.apply:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = db_path.with_name(f"{db_path.name}.backup-{ts}")
        shutil.copy2(db_path, backup_path)
        print(f"Backup written: {backup_path}")

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        summary = _summary(conn, keep_ids, keep_empty=args.keep_empty)
        if args.apply and summary["to_delete"]:
            # Chunk the IN clause so SQLite's variable-limit doesn't bite
            # on huge keep-sets.
            chunk = 500
            cur = conn.cursor()
            to_delete = summary["to_delete"]
            for i in range(0, len(to_delete), chunk):
                batch = to_delete[i : i + chunk]
                placeholders = ",".join("?" * len(batch))
                cur.execute(f"DELETE FROM sessions WHERE id IN ({placeholders})", batch)
            conn.commit()
            conn.execute("VACUUM")
        _print_report(summary, applied=args.apply)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
