"""Lake helpers. Tests stub DuckDB and the Parquet writer. No Postgres."""

import atexit

import duckdb
import pytest

from src.data import historical
from src.data.historical import query_recent


class _Result:
    def pl(self):
        return []


class _Conn:
    def __init__(self):
        self.calls = []

    def execute(self, query, params=None):
        self.calls.append((query, params))
        return _Result()


def _stub(monkeypatch):
    conn = _Conn()
    monkeypatch.setattr(duckdb, "connect", lambda *args, **kwargs: conn)
    return conn


def test_query_recent_binds_platform_id_and_limit(monkeypatch):
    conn = _stub(monkeypatch)
    payload = "uav-01' OR '1'='1"
    query_recent(payload, limit=5)
    sql, params = conn.calls[0]
    assert sql.count("?") == 2
    assert "WHERE platform_id = ?" in sql
    assert "ORDER BY ts DESC LIMIT ?" in sql
    assert "union_by_name=true" in sql
    assert payload not in sql
    assert params == [payload, 5]


def test_query_recent_rejects_a_non_integer_limit(monkeypatch):
    conn = _stub(monkeypatch)
    with pytest.raises(ValueError, match="limit must be an integer"):
        query_recent("uav-01", limit="10; DROP TABLE telemetry")
    assert conn.calls == []
    with pytest.raises(ValueError, match="limit must be an integer"):
        query_recent("uav-01", limit=-1)
    assert conn.calls == []


def test_query_recent_omits_where_without_a_platform_id(monkeypatch):
    for platform_id in (None, ""):
        conn = _stub(monkeypatch)
        query_recent(platform_id, limit=3)
        sql, params = conn.calls[0]
        assert "WHERE" not in sql
        assert params == [3]


class _FakeTimer:
    def __init__(self, interval, function):
        self.interval = interval
        self.function = function
        self.daemon = False
        self.cancelled = False
        self.started = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


def _quiet_buffer():
    timer = historical._flush_timer
    if timer is not None:
        timer.cancel()
        historical._flush_timer = None
    historical._pending.clear()


def test_buffer_telemetry_flushes_after_inactivity(monkeypatch):
    _quiet_buffer()
    monkeypatch.setattr(historical, "TELEMETRY_FLUSH_S", 12.5)
    monkeypatch.setattr(historical, "TELEMETRY_BATCH_ROWS", 500)
    armed = []

    def fake_timer(interval, function):
        timer = _FakeTimer(interval, function)
        armed.append(timer)
        return timer

    monkeypatch.setattr(historical, "Timer", fake_timer)
    parts = []

    def append(records):
        parts.append(list(records))
        return "part"

    monkeypatch.setattr(historical, "append_telemetry", append)
    first = {"platform_id": "uav-01"}
    second = {"platform_id": "uav-02"}
    try:
        assert historical.buffer_telemetry(first) is None
        assert parts == []
        assert armed[0].started is True
        assert armed[0].daemon is True
        assert armed[0].interval == 12.5
        assert armed[0].cancelled is False

        assert historical.buffer_telemetry(second) is None
        assert parts == []
        assert armed[0].cancelled is True
        assert armed[1].started is True
        assert armed[1].interval == 12.5
        assert armed[1].cancelled is False

        assert armed[1].function() == "part"
        assert parts == [[first, second]]
        assert armed[1].function() is None
        assert len(parts) == 1

        _quiet_buffer()
        armed.clear()
        parts.clear()
        monkeypatch.setattr(historical, "TELEMETRY_BATCH_ROWS", 2)
        third = {"platform_id": "ugv-01"}
        fourth = {"platform_id": "ugv-02"}
        assert historical.buffer_telemetry(third) is None
        assert parts == []
        early = armed[0]
        assert historical.buffer_telemetry(fourth) == "part"
        assert parts == [[third, fourth]]
        assert early.cancelled is True
        assert early.function() is None
        assert len(parts) == 1
    finally:
        _quiet_buffer()


def test_process_exit_flushes_the_partial_batch(monkeypatch):
    _quiet_buffer()
    monkeypatch.setattr(historical, "TELEMETRY_BATCH_ROWS", 500)
    monkeypatch.setattr(historical, "Timer", _FakeTimer)
    parts = []

    def append(records):
        parts.append(list(records))
        return "part"

    monkeypatch.setattr(historical, "append_telemetry", append)
    registered = []

    def record_register(func, *args, **kwargs):
        registered.append(func)

    row = {"platform_id": "uav-01"}
    try:
        assert historical.buffer_telemetry(row) is None
        assert parts == []
        monkeypatch.setattr(atexit, "register", record_register)
        historical._exit_flush_installed = False
        historical._install_exit_flush()
        historical._install_exit_flush()
        assert registered == [historical._flush_on_exit]
        assert historical._flush_on_exit() == "part"
        assert parts == [[row]]
        assert historical._flush_on_exit() is None
        assert len(parts) == 1
    finally:
        historical._exit_flush_installed = True
        _quiet_buffer()


def test_buffer_telemetry_writes_one_file_per_full_batch(monkeypatch):
    historical._pending.clear()
    monkeypatch.setattr(historical, "TELEMETRY_BATCH_ROWS", 2)
    parts = []

    def append(records):
        parts.append(list(records))
        return "part"

    monkeypatch.setattr(historical, "append_telemetry", append)
    first = {"platform_id": "uav-01"}
    second = {"platform_id": "uav-02"}
    third = {"platform_id": "ugv-01"}
    try:
        assert historical.buffer_telemetry(first) is None
        assert parts == []
        assert historical.buffer_telemetry(second) == "part"
        assert parts == [[first, second]]
        assert historical.buffer_telemetry(third) is None
        assert parts == [[first, second]]
        assert historical.flush_telemetry() == "part"
        assert parts == [[first, second], [third]]
        assert historical.flush_telemetry() is None
        assert len(parts) == 2
    finally:
        _quiet_buffer()


def test_query_recent_escapes_a_quote_in_the_lake_path(monkeypatch, tmp_path):
    lake = tmp_path / "o'lake"
    monkeypatch.setattr("src.data.historical.LAKE_ROOT", lake)
    conn = _stub(monkeypatch)
    query_recent("uav-01", limit=1)
    sql, _params = conn.calls[0]
    raw = str(lake / "telemetry" / "**" / "*.parquet")
    assert raw.replace("'", "''") in sql
    assert raw not in sql


def test_failed_flush_keeps_rows_for_retry(monkeypatch):
    rows = [{"value": 1}]
    monkeypatch.setattr(historical, "_pending", rows.copy())

    def fail_write(records):
        raise OSError("disk full")

    monkeypatch.setattr(historical, "append_telemetry", fail_write)
    with pytest.raises(OSError, match="disk full"):
        historical.flush_telemetry()
    assert historical._pending == rows
