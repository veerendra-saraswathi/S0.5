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


def test_partial_marker_never_authorizes_deletion(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(retention, "LAKE_ROOT", tmp_path)
    marker = tmp_path / "_markers" / "events-day.ok"
    write_text = Path.write_text
    deletions = []

    def interrupted_write(path, text):
        write_text(path, text[:1])
        drop_after_marker(marker, delete=deletions.append)
        raise OSError("write interrupted")

    monkeypatch.setattr(Path, "write_text", interrupted_write)
    result = export_for_drop(
        [{}] * 12, table="events", range_key="day", write=lambda rows, path: path
    )
    assert result is None
    assert deletions == []
    assert not any(path.is_file() for path in marker.parent.iterdir())


def test_repeat_export_revokes_old_marker_before_writer_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "LAKE_ROOT", tmp_path)
    key = {"table": "events", "range_key": "day"}
    previous = export_for_drop([{}], **key, write=lambda rows, path: path)
    calls = []

    def failed_write(rows, path):
        drop_after_marker(previous["marker"], delete=calls.append)
        raise OSError("disk full")

    assert export_for_drop([{}, {}], **key, write=failed_write) is None
    assert drop_after_marker(previous["marker"], delete=calls.append) is None
    assert calls == []


def test_export_cannot_replace_range_during_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(retention, "LAKE_ROOT", tmp_path)
    key = {"table": "events", "range_key": "day"}
    previous = export_for_drop([{}], **key, write=lambda rows, path: path)
    writes = []

    def delete(count):
        assert export_for_drop([{}, {}], **key, write=lambda *args: writes.append(args)) is None

    assert drop_after_marker(previous["marker"], delete=delete) == 1
    assert writes == []
    assert export_for_drop([{}, {}], **key, write=lambda rows, path: path)["count"] == 2


def test_crashed_export_releases_only_its_range_lock(monkeypatch, tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    monkeypatch.setattr(retention, "LAKE_ROOT", tmp_path)
    key = {"table": "events", "range_key": "day"}
    previous = export_for_drop([{}], **key, write=lambda rows, path: path)

    child_code = """
import sys
from pathlib import Path
from src.data import retention

retention.LAKE_ROOT = Path(sys.argv[1])

def paused_write(rows, path):
    print("locked", flush=True)
    sys.stdin.readline()
    return path

retention.export_for_drop([{}], table="events", range_key="day", write=paused_write)
"""
    from concurrent.futures import ThreadPoolExecutor

    root = Path(retention.__file__).resolve().parents[2]
    with subprocess.Popen(
        [sys.executable, "-c", child_code, str(tmp_path)],
        cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    ) as child, ThreadPoolExecutor(max_workers=1) as reader:
        try:
            assert reader.submit(child.stdout.readline).result(timeout=10) == "locked\n"
            calls = []
            assert export_for_drop([{}], **key, write=lambda *args: calls.append(args)) is None
            assert drop_after_marker(previous["marker"], delete=calls.append) is None
            assert calls == []
            other = export_for_drop([{}], table="events", range_key="other",
                                    write=lambda rows, path: path)
            assert other["count"] == 1
        finally:
            child.kill()
            child.wait(timeout=10)

    assert not Path(previous["marker"]).exists()
    retry = export_for_drop([{}, {}], **key, write=lambda rows, path: path)
    assert Path(retry["marker"]).read_text() == "2"


def test_export_records_submitted_count_when_writer_consumes_batch(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setattr(retention, "LAKE_ROOT", tmp_path)
    written = []

    def write(rows, path):
        written.extend(rows)
        rows.clear()
        return path

    result = export_for_drop(
        [{"id": 1}, {"id": 2}], table="events", range_key="day", write=write
    )
    assert len(written) == 2
    assert result["count"] == 2
    assert Path(result["marker"]).read_text() == "2"
    calls = []
    assert drop_after_marker(result["marker"], delete=calls.append) == 2
    assert calls == [2]
