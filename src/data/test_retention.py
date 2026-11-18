"""export_for_drop writes a marker file only after the stubbed writer succeeds."""

from src.data import retention
from src.data.retention import drop_after_marker, export_for_drop


def test_export_for_drop_writes_the_marker_only_after_a_successful_write(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(retention, "LAKE_ROOT", tmp_path)
    rows = [{"asset_id": "uav-01"}, {"asset_id": "uav-02"}]
    calls = []

    def write(got, path):
        calls.append((got, path))
        return "part"

    result = export_for_drop(
        rows, table="telemetry", range_key="2026-04-14", write=write
    )
    parquet = str(tmp_path / "telemetry" / "2026-04-14.parquet")
    marker = tmp_path / "_markers" / "telemetry-2026-04-14.ok"
    assert calls == [(rows, parquet)]
    assert result == {"marker": str(marker), "count": 2, "parquet": parquet}
    assert marker.read_text() == "2"
    assert not (tmp_path / "telemetry" / "2026-04-14.parquet").exists()

    def boom(got, path):
        raise RuntimeError("copy failed")

    assert (
        export_for_drop(rows, table="telemetry", range_key="2026-04-15", write=boom)
        is None
    )
    assert not (tmp_path / "_markers" / "telemetry-2026-04-15.ok").exists()

    def silent(got, path):
        return None

    assert (
        export_for_drop(rows, table="telemetry", range_key="2026-04-16", write=silent)
        is None
    )
    assert not (tmp_path / "_markers" / "telemetry-2026-04-16.ok").exists()

    calls.clear()
    assert (
        export_for_drop([], table="telemetry", range_key="2026-04-17", write=write)
        is None
    )
    assert calls == []
    assert not (tmp_path / "_markers" / "telemetry-2026-04-17.ok").exists()


def test_drop_after_marker_calls_the_deleter_only_for_a_positive_count(tmp_path):
    calls = []

    def delete(count):
        calls.append(count)

    marker = tmp_path / "_markers" / "telemetry-2026-04-14.ok"
    marker.parent.mkdir()
    marker.write_text("2")
    assert drop_after_marker(marker, delete=delete) == 2
    assert calls == [2]
    assert marker.read_text() == "2"

    calls.clear()
    assert drop_after_marker(tmp_path / "missing.ok", delete=delete) is None
    empty = tmp_path / "empty.ok"
    empty.write_text("")
    assert drop_after_marker(empty, delete=delete) is None
    zero = tmp_path / "zero.ok"
    zero.write_text("0")
    assert drop_after_marker(zero, delete=delete) is None
    assert calls == []

    def boom(count):
        raise RuntimeError("drop failed")

    assert drop_after_marker(marker, delete=boom) is None
