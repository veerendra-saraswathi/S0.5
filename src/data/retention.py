"""Export marker for a later retention drop. No database and no Parquet file."""

from pathlib import Path

LAKE_ROOT = Path("data/lake")


def export_for_drop(rows: list[dict], *, table: str, range_key: str, write) -> dict | None:
    """Copy rows through write, then write the marker file. None means do not drop."""
    if not rows:
        return None
    parquet = str(LAKE_ROOT / table / f"{range_key}.parquet")
    try:
        written = write(rows, parquet)
    except Exception:
        return None
    if written is None:
        return None
    marker = LAKE_ROOT / "_markers" / f"{table}-{range_key}.ok"
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(len(rows)))
    except Exception:
        return None
    return {
        "marker": str(marker),
        "count": len(rows),
        "parquet": parquet,
    }


def drop_after_marker(marker, *, delete) -> int | None:
    """Call delete only when the marker file holds a positive count."""
    path = Path(marker)
    if not path.is_file():
        return None
    try:
        count = int(path.read_text().strip())
    except (OSError, ValueError):
        return None
    if count <= 0:
        return None
    try:
        delete(count)
    except Exception:
        return None
    return count
