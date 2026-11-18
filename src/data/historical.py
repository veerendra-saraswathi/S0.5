import atexit
import threading

import polars as pl
from datetime import datetime, timezone
from pathlib import Path

LAKE_ROOT = Path("data/lake")
LAKE_ROOT.mkdir(parents=True, exist_ok=True)

TELEMETRY_BATCH_ROWS = 500
TELEMETRY_FLUSH_S = 5.0
_pending: list[dict] = []
_pending_lock = threading.Lock()
_flush_timer: threading.Timer | None = None
Timer = threading.Timer

def append_telemetry(records: list[dict]) -> str | None:
    if not records:
        return None
    df = pl.DataFrame(records)
    if "ts" not in df.columns:
        df = df.with_columns(pl.lit(datetime.now(timezone.utc).isoformat()).alias("ts"))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = LAKE_ROOT / "telemetry" / f"date={today}"
    out_dir.mkdir(parents=True, exist_ok=True)

    fname = out_dir / f"part-{datetime.now(timezone.utc).strftime('%H%M%S%f')}.parquet"
    df.write_parquet(fname)
    return str(fname)


def _cancel_flush_timer_locked() -> None:
    global _flush_timer
    if _flush_timer is not None:
        _flush_timer.cancel()
        _flush_timer = None


def _arm_flush_timer_locked() -> None:
    global _flush_timer
    _cancel_flush_timer_locked()
    timer = Timer(TELEMETRY_FLUSH_S, flush_telemetry)
    timer.daemon = True
    _flush_timer = timer
    timer.start()


def buffer_telemetry(record: dict) -> str | None:
    """Hold one row. A full batch, or 5 s without a newer row, becomes one file."""
    with _pending_lock:
        _pending.append(record)
        if len(_pending) >= TELEMETRY_BATCH_ROWS:
            _cancel_flush_timer_locked()
            return _flush_locked()
        _arm_flush_timer_locked()
    return None


def flush_telemetry() -> str | None:
    """Write any pending rows as one Parquet file."""
    with _pending_lock:
        _cancel_flush_timer_locked()
        return _flush_locked()


_exit_flush_installed = False


def _flush_on_exit() -> str | None:
    return flush_telemetry()


def _install_exit_flush() -> None:
    global _exit_flush_installed
    if _exit_flush_installed:
        return
    atexit.register(_flush_on_exit)
    _exit_flush_installed = True


_install_exit_flush()


def _flush_locked() -> str | None:
    if not _pending:
        return None
    rows = list(_pending)
    _pending.clear()
    return append_telemetry(rows)


def query_recent(platform_id: str | None = None, limit: int = 100):
    import duckdb

    try:
        bound_limit = int(limit)
    except (TypeError, ValueError):
        raise ValueError("limit must be an integer") from None
    if bound_limit < 0:
        raise ValueError("limit must be an integer")

    con = duckdb.connect()
    path = str(LAKE_ROOT / "telemetry" / "**" / "*.parquet").replace("'", "''")
    q = f"SELECT * FROM read_parquet('{path}', union_by_name=true)"
    params: list = []
    if platform_id:
        q += " WHERE platform_id = ?"
        params.append(str(platform_id))
    q += " ORDER BY ts DESC LIMIT ?"
    params.append(bound_limit)
    return con.execute(q, params).pl()
