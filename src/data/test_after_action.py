"""After-action Parquet contains the mission's telemetry, commands, events, and alerts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest
import polars as pl
import pyarrow.parquet as pq

from src.data.after_action import write_after_action
from src.data_services.repositories import get_repositories

WHEN = datetime(2026, 10, 12, 15, 0, tzinfo=timezone.utc)


def test_export_writes_one_parquet_per_table(tmp_path, monkeypatch):
    monkeypatch.delenv("MINIO_ENDPOINT", raising=False)
    asset_id = f"export-{uuid4()}"
    other_id = f"export-other-{uuid4()}"
    mission_id = f"mission-{uuid4()}"
    repos = get_repositories()
    repos.telemetry.insert(asset_id, WHEN, 17.4, 78.5, 40.0, 10.0, 5.0, 90.0, "mission", "auto")
    repos.telemetry.insert(other_id, WHEN, 1.0, 2.0, 3.0, 0.0, 0.0, 50.0, "idle", "manual")
    repos.commands.insert(f"cmd-{uuid4()}", asset_id, "goto", {"lat": 17.4}, "operator-1", WHEN)
    event_id = f"evt-{uuid4()}"
    event_data = {"source": "archive-test", "sequence": 3}
    repos.events.insert(event_id, WHEN, "command", "goto", asset_id, "info", event_data)
    repos.alerts.insert(f"alt-{uuid4()}", WHEN, asset_id, "warning", "zone", {"zone_id": "z"})

    result = write_after_action(mission_id, [asset_id], tmp_path / mission_id)
    assert result["upload_status"] == "not_configured"
    assert result["uploaded"] is False
    assert set(result["files"]) == {"telemetry", "commands", "events", "alerts"}

    telemetry = pl.read_parquet(result["files"]["telemetry"])
    commands = pl.read_parquet(result["files"]["commands"])
    events = pl.read_parquet(result["files"]["events"])
    alerts = pl.read_parquet(result["files"]["alerts"])
    assert telemetry.height == 1
    assert telemetry["asset_id"][0] == asset_id
    assert telemetry["mission_id"][0] == mission_id
    assert telemetry["lat"][0] == 17.4
    assert commands.height == 1
    assert commands["command_type"][0] == "goto"
    assert events.height == 1
    event = events.row(0, named=True)
    assert event["event_id"] == event_id
    assert datetime.fromisoformat(event["time"]) == WHEN
    assert event["asset_id"] == asset_id
    assert event["mission_id"] == mission_id
    assert json.loads(event["data"]) == event_data
    assert alerts.height == 1
    assert alerts["level"][0] == "warning"


def test_export_writes_an_empty_schema(tmp_path):
    mission_id = f"empty-{uuid4()}"
    result = write_after_action(mission_id, [f"nobody-{uuid4()}"], tmp_path / mission_id)
    for name in ("telemetry", "commands", "events", "alerts"):
        frame = pl.read_parquet(result["files"][name])
        assert frame.height == 0
        assert "mission_id" in frame.columns
        assert "asset_id" in frame.columns


def test_event_archive_declares_scope_even_when_empty(tmp_path):
    result = write_after_action("empty-archive", [], tmp_path)
    metadata = pq.read_metadata(result["files"]["events"]).metadata
    assert metadata[b"samanvaya.archive.schema"] == b"events.v1"
    assert metadata[b"samanvaya.archive.mission_id_source"] == b"export_request"
    assert metadata[b"samanvaya.archive.selection"] == b"asset_id"


def test_failed_refresh_preserves_published_files(tmp_path, monkeypatch):
    monkeypatch.delenv("MINIO_ENDPOINT", raising=False)
    result = write_after_action("archive", [], tmp_path)
    paths = [Path(value) for value in result["files"].values()]
    contents = set(tmp_path.rglob("*"))
    original = {path: path.read_bytes() for path in paths}

    def interrupted(table, destination, **options):
        Path(destination).write_bytes(b"incomplete")
        assert all(path.read_bytes() == original[path] for path in paths)
        raise OSError("interrupted export")

    with monkeypatch.context() as patch:
        patch.setattr(pq, "write_table", interrupted)
        with pytest.raises(OSError, match="interrupted export"):
            write_after_action("archive", [], tmp_path)

    assert set(tmp_path.rglob("*")) == contents
    assert all(path.read_bytes() == original[path] for path in paths)
    assert write_after_action("archive", [], tmp_path)["generation"] != result["generation"]


def test_upload_includes_only_files_from_current_export(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    uploads = []

    class Client:
        def bucket_exists(self, bucket):
            return True

        def fput_object(self, bucket, key, path):
            uploads.append((key, path))

    monkeypatch.setenv("MINIO_ENDPOINT", "archive.test")
    monkeypatch.setitem(sys.modules, "minio", SimpleNamespace(Minio=lambda *a, **kw: Client()))
    (tmp_path / "previous.parquet").write_bytes(b"previous job")

    result = write_after_action("archive", [], tmp_path)

    assert result["uploaded"]
    expected = []
    for name, path in result["files"].items():
        expected.append((f"archive/generations/{result['generation']}/{name}.parquet", path))
        expected.append((f"archive/{name}.parquet", path))
    assert sorted(uploads[:-2]) == sorted(expected)
    assert uploads[-2] == (f"archive/generations/{result['generation']}/manifest.json", result["manifest"])
    assert uploads[-1] == ("archive/manifest.json", result["manifest"])


def test_reader_pinned_before_refresh_finishes_on_original_generation(tmp_path, monkeypatch):
    from src.data import after_action

    monkeypatch.delenv("MINIO_ENDPOINT", raising=False)
    monkeypatch.setattr(after_action, "_collect", lambda ids: {
        name: [{"asset_id": ids[0]}] for name in after_action.TABLES
    })
    first = write_after_action("archive", ["old"], tmp_path)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    entries = iter(manifest["files"].values())

    def asset(entry):
        return pl.read_parquet(tmp_path / entry)["asset_id"].item()

    assert asset(next(entries)) == "old"
    second = write_after_action("archive", ["new"], tmp_path)
    assert [asset(entry) for entry in entries] == ["old"] * 3
    latest = json.loads((tmp_path / "manifest.json").read_text())
    assert first["generation"] == manifest["generation"] != latest["generation"]
    assert latest == json.loads(Path(second["manifest"]).read_text())
    assert all(asset(entry) == "new" for entry in latest["files"].values())
    assert all(asset(f"{name}.parquet") == "new" for name in latest["files"])


@pytest.mark.parametrize("failure_at", ["events.parquet", "generation manifest", "current manifest"])
def test_interrupted_upload_preserves_remote_snapshot_and_allows_retry(tmp_path, monkeypatch, failure_at):
    import sys
    from types import SimpleNamespace

    objects = {}
    failures = []
    interrupt = False

    class Client:
        def bucket_exists(self, bucket):
            return True

        def fput_object(self, bucket, key, path):
            if key == "archive/manifest.json":
                stage = "current manifest"
            elif key.endswith("/manifest.json"):
                stage = "generation manifest"
            else:
                stage = key.rsplit("/", 1)[-1]
            if interrupt and stage == failure_at:
                failures.append(key)
                raise OSError("interrupted upload")
            objects[key] = Path(path).read_bytes()

    monkeypatch.setenv("MINIO_ENDPOINT", "archive.test")
    monkeypatch.setitem(sys.modules, "minio", SimpleNamespace(Minio=lambda *a, **kw: Client()))

    first = write_after_action("archive", [], tmp_path)
    assert first["uploaded"]
    current_key = "archive/manifest.json"
    original = objects[current_key]
    pinned = "archive/generations/" + first["generation"] + "/manifest.json"

    interrupt = True
    failed = write_after_action("archive", [], tmp_path)
    assert len(failures) == 1
    assert failed["upload_status"] == "failed"
    assert not failed["uploaded"]
    assert objects[current_key] == original
    assert json.loads(Path(failed["manifest"]).read_bytes())["generation"] == failed["generation"]

    interrupt = False
    retry = write_after_action("archive", [], tmp_path)
    assert retry["upload_status"] == "uploaded"
    assert retry["uploaded"]
    assert json.loads(objects[current_key])["generation"] == retry["generation"]
    assert objects[pinned] == original
    for result, manifest_key in [(first, pinned), (retry, current_key)]:
        for name, entry in json.loads(objects[manifest_key])["files"].items():
            assert objects[f"archive/{entry}"] == Path(result["files"][name]).read_bytes()


def test_configured_upload_without_minio_client_keeps_local_export(tmp_path, monkeypatch):
    import sys

    monkeypatch.setenv("MINIO_ENDPOINT", "archive.test")
    monkeypatch.setitem(sys.modules, "minio", None)
    result = write_after_action("archive", [], tmp_path)
    assert result["upload_status"] == "client_unavailable"
    assert result["uploaded"] is False
    assert Path(result["manifest"]).is_file()
    assert all(Path(path).is_file() for path in result["files"].values())


@pytest.mark.parametrize("code, expected", [
    ("BucketAlreadyOwnedByYou", "uploaded"),
    ("BucketAlreadyExists", "failed"),
    ("AccessDenied", "failed"),
])
def test_bucket_creation_conflict(tmp_path, monkeypatch, code, expected):
    import sys
    from types import SimpleNamespace

    class S3Error(Exception):
        def __init__(self, error_code):
            super().__init__(error_code)
            self.code = error_code

    keys = []

    class Client:
        def bucket_exists(self, bucket):
            return False

        def make_bucket(self, bucket):
            raise S3Error(code)

        def fput_object(self, bucket, key, path):
            keys.append(key)

    monkeypatch.setenv("MINIO_ENDPOINT", "archive.test")
    monkeypatch.setitem(sys.modules, "minio", SimpleNamespace(Minio=lambda *a, **kw: Client()))
    monkeypatch.setitem(sys.modules, "minio.error", SimpleNamespace(S3Error=S3Error))
    result = write_after_action("archive", [], tmp_path)
    assert result["upload_status"] == expected
    assert Path(result["manifest"]).is_file()
    if expected == "uploaded":
        assert keys[-1] == "archive/manifest.json"
    else:
        assert keys == []
