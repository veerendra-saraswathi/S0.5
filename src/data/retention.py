"""Publish export markers and serialize retention operations for each range."""

import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import uuid4

import polars as pl

LAKE_ROOT = Path("data/lake")
MARKER_FORMAT = "s05.parquet-row-count.v1"


@contextmanager
def _range_lock(marker):
    # SQLite releases the file lock even if the process exits during a callback.
    locks = marker.parent / ".locks"
    locks.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(locks / marker.name, timeout=0)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        yield


def export_for_drop(rows: list[dict], *, table: str, range_key: str, write) -> dict | None:
    """Revoke prior approval for this range, export, then publish its row count."""
    marker = LAKE_ROOT / "_markers" / f"{table}-{range_key}.ok"
    parquet = LAKE_ROOT / table / f"{range_key}.parquet"
    if not rows and not marker.exists():
        return None
    try:
        with _range_lock(marker):
            marker.unlink(missing_ok=True)
            count = len(rows)
            if not count:
                return None
            parquet.parent.mkdir(parents=True, exist_ok=True)
            staged = parquet.with_suffix(f".{uuid4().hex}.tmp")
            try:
                if write(rows, str(staged)) is None:
                    return None
                if pl.read_parquet(staged, glob=False).height != count:
                    return None
                staged.replace(parquet)
            finally:
                staged.unlink(missing_ok=True)
            pending = marker.with_suffix(f".{uuid4().hex}.tmp")
            try:
                pending.write_text(json.dumps({"format": MARKER_FORMAT, "row_count": count}))
                pending.replace(marker)
            finally:
                pending.unlink(missing_ok=True)
    except Exception:
        return None
    return {"marker": str(marker), "count": count, "parquet": str(parquet)}


def drop_after_marker(marker, *, delete) -> int | None:
    """Hold the same range lock while checking the count and invoking delete."""
    path = Path(marker)
    if not path.is_file():
        return None
    try:
        with _range_lock(path):
            record = json.loads(path.read_text())
            if not isinstance(record, dict) or record.get("format") != MARKER_FORMAT:
                return None
            count = record.get("row_count")
            if type(count) is not int or count <= 0:
                return None
            delete(count)
    except Exception:
        return None
    return count
