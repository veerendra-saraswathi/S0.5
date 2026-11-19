"""Opt-in readback against a disposable MinIO endpoint."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import polars as pl
import pytest

from src.data.after_action import write_after_action
from src.data_services.repositories import get_repositories


@pytest.mark.skipif(os.getenv("S05_TEST_MINIO") != "1", reason="requires disposable MinIO")
def test_read_published_generation(tmp_path, monkeypatch):
    from minio import Minio

    bucket = f"archive-test-{uuid4().hex}"
    monkeypatch.setenv("MINIO_BUCKET", bucket)
    client = Minio(
        os.environ["MINIO_ENDPOINT"],
        access_key=os.environ["MINIO_ACCESS_KEY"],
        secret_key=os.environ["MINIO_SECRET_KEY"],
        secure=os.getenv("MINIO_SECURE", "").lower() in {"1", "true", "yes"},
    )
    asset = f"sample-{uuid4().hex}"
    events = get_repositories().events
    first_event, second_event = f"{asset}-A", f"{asset}-B"
    when = datetime.now(timezone.utc)
    events.insert(first_event, when, "review", "first", asset, "info", {})
    exported = write_after_action("readback", [asset], tmp_path / "export")
    assert exported["uploaded"], "archive upload failed"
    events.insert(second_event, when, "review", "second", asset, "info", {})
    refreshed = write_after_action("readback", [asset], tmp_path / "export")
    assert refreshed["uploaded"]
    assert refreshed["generation"] != exported["generation"]
    manifest_path = tmp_path / "downloaded-manifest.json"
    client.fget_object(bucket, "readback/manifest.json", str(manifest_path))
    current = json.loads(manifest_path.read_text())
    assert current["generation"] == refreshed["generation"]
    latest_events = tmp_path / "latest-events.parquet"
    client.fget_object(bucket, f"readback/{current['files']['events']}", str(latest_events))
    assert sorted(pl.read_parquet(latest_events)["event_id"].to_list()) == [first_event, second_event]
    pinned_key = f"readback/generations/{exported['generation']}/manifest.json"
    pinned_path = tmp_path / "downloaded-first-manifest.json"
    client.fget_object(bucket, pinned_key, str(pinned_path))
    manifest = json.loads(pinned_path.read_text())
    assert pinned_path.read_bytes() == Path(exported["manifest"]).read_bytes()
    assert manifest["generation"] == exported["generation"]
    assert set(manifest["files"]) == {"telemetry", "commands", "events", "alerts"}
    for name, relative in manifest["files"].items():
        downloaded = tmp_path / f"{name}.parquet"
        assert relative == f"generations/{exported['generation']}/{name}.parquet"
        client.fget_object(bucket, f"readback/{relative}", str(downloaded))
        assert downloaded.read_bytes() == Path(exported["files"][name]).read_bytes()
    assert pl.read_parquet(tmp_path / "events.parquet")["event_id"].to_list() == [first_event]
