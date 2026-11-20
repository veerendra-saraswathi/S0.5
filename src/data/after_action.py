"""After-action Parquet for one mission: telemetry, commands, events, alerts.

Files land in a local folder. When MINIO_ENDPOINT is set and the minio
package imports, the same files are uploaded. A missing package or endpoint
leaves the local folder as the export.
"""

from __future__ import annotations

import json
import os
import shutil
from contextlib import closing
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import polars as pl
import pyarrow.parquet as pq

from src.data_services.repositories import get_repositories

TABLES = ("telemetry", "commands", "events", "alerts")

_SCHEMAS: dict[str, dict[str, pl.DataType]] = {
    "telemetry": {
        "mission_id": pl.Utf8,
        "asset_id": pl.Utf8,
        "time": pl.Utf8,
        "lat": pl.Float64,
        "lon": pl.Float64,
        "alt": pl.Float64,
        "heading": pl.Float64,
        "speed": pl.Float64,
        "battery_percent": pl.Float64,
        "status": pl.Utf8,
        "mode": pl.Utf8,
    },
    "commands": {
        "mission_id": pl.Utf8,
        "command_id": pl.Utf8,
        "asset_id": pl.Utf8,
        "command_type": pl.Utf8,
        "parameters": pl.Utf8,
        "issued_by": pl.Utf8,
        "issued_at": pl.Utf8,
    },
    "events": {
        "mission_id": pl.Utf8,
        "event_id": pl.Utf8,
        "time": pl.Utf8,
        "event_type": pl.Utf8,
        "asset_id": pl.Utf8,
        "message": pl.Utf8,
        "severity": pl.Utf8,
        "data": pl.Utf8,
    },
    "alerts": {
        "mission_id": pl.Utf8,
        "alert_id": pl.Utf8,
        "time": pl.Utf8,
        "asset_id": pl.Utf8,
        "level": pl.Utf8,
        "message": pl.Utf8,
        "payload": pl.Utf8,
    },
}

_DUCK = {
    "telemetry": """
        SELECT asset_id, timestamp AS time, lat, lon, alt, heading, speed,
               battery_percent, status, mode
        FROM telemetry WHERE asset_id IN ({marks})
    """,
    "commands": """
        SELECT command_id, asset_id, command_type, parameters, issued_by, issued_at
        FROM commands WHERE asset_id IN ({marks})
    """,
    "events": """
        SELECT event_id, timestamp AS time, event_type, asset_id, message, severity, data
        FROM events WHERE asset_id IN ({marks})
    """,
    "alerts": """
        SELECT alert_id, timestamp AS time, asset_id, level, message, payload
        FROM alerts WHERE asset_id IN ({marks})
    """,
}

_POSTGRES = {
    "telemetry": """
        SELECT asset_id, "time" AS time, lat, lon, alt, heading, speed,
               battery_percent, status, mode
        FROM telemetry WHERE asset_id IN ({marks})
    """,
    "commands": """
        SELECT command_id, asset_id, command_type, parameters, issued_by, issued_at
        FROM commands WHERE asset_id IN ({marks})
    """,
    "events": """
        SELECT event_id, "time" AS time, event_type, asset_id, message, severity, data
        FROM events WHERE asset_id IN ({marks})
    """,
    "alerts": """
        SELECT alert_id, "time" AS time, asset_id, level, message, payload
        FROM alerts WHERE asset_id IN ({marks})
    """,
}


def _safe_mission_id(mission_id: str) -> str:
    cleaned = "".join(char for char in mission_id if char.isalnum() or char in "-_")
    return cleaned or "mission"


def _norm(value):
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    if isinstance(value, bytes):
        return value.decode()
    return value


def _fetch_duck(con, sql: str, asset_ids: list[str]) -> list[dict]:
    cursor = con.execute(sql, asset_ids)
    names = [item[0] for item in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _fetch_postgres(conn, sql: str, binds: dict[str, str]) -> list[dict]:
    from sqlalchemy import text

    rows = conn.execute(text(sql), binds).mappings()
    return [dict(row) for row in rows]


def _collect(asset_ids: list[str]) -> dict[str, list[dict]]:
    empty = {name: [] for name in TABLES}
    if not asset_ids:
        return empty
    repos = get_repositories()
    if getattr(repos, "backend", "") == "postgres":
        binds = {f"a{index}": asset_id for index, asset_id in enumerate(asset_ids)}
        marks = ", ".join(f":{key}" for key in binds)
        with repos.engine.connect() as conn:
            conn.execution_options(isolation_level="REPEATABLE READ")
            with conn.begin():
                return {
                    name: _fetch_postgres(conn, sql.format(marks=marks), binds)
                    for name, sql in _POSTGRES.items()
                }

    marks = ", ".join("?" for _ in asset_ids)
    # A child cursor has its own transaction, independent of repository writers.
    with closing(repos.database.con.cursor()) as reader:
        reader.execute("BEGIN TRANSACTION")
        rows = {
            name: _fetch_duck(reader, sql.format(marks=marks), asset_ids)
            for name, sql in _DUCK.items()
        }
        reader.execute("COMMIT")
    return rows


def _frame(mission_id: str, name: str, rows: list[dict]) -> pl.DataFrame:
    schema = _SCHEMAS[name]
    records = []
    for row in rows:
        item = {"mission_id": mission_id}
        for key in schema:
            if key == "mission_id":
                continue
            item[key] = _norm(row.get(key))
        records.append(item)
    if not records:
        return pl.DataFrame(schema=schema)
    return pl.DataFrame(records, schema=schema)


def _upload(files: dict[str, str], mission_id: str, manifest: Path, relative: Path) -> str:
    endpoint = os.environ.get("MINIO_ENDPOINT", "").strip()
    if not endpoint:
        return "not_configured"
    try:
        from minio import Minio
    except ImportError:
        return "client_unavailable"
    secure = os.environ.get("MINIO_SECURE", "").lower() in {"1", "true", "yes"}
    client = Minio(
        endpoint,
        access_key=os.environ.get("MINIO_ACCESS_KEY", ""),
        secret_key=os.environ.get("MINIO_SECRET_KEY", ""),
        secure=secure,
    )
    bucket = os.environ.get("MINIO_BUCKET", "cnc-after-action")
    if not client.bucket_exists(bucket):
        from minio.error import S3Error

        try:
            client.make_bucket(bucket)
        except S3Error as exc:
            # Another exporter can create our bucket after the existence check.
            if exc.code != "BucketAlreadyOwnedByYou":
                raise
    for path in sorted(files.values()):
        name = Path(path).name
        client.fput_object(bucket, f"{mission_id}/{relative.as_posix()}/{name}", path)
        client.fput_object(bucket, f"{mission_id}/{name}", path)
    client.fput_object(bucket, f"{mission_id}/{relative.as_posix()}/manifest.json", str(manifest))
    client.fput_object(bucket, f"{mission_id}/manifest.json", str(manifest))
    return "uploaded"


def write_after_action(
    mission_id: str,
    asset_ids: list[str] | None = None,
    folder: str | Path | None = None,
) -> dict:
    """Write four Parquet files for the assets assigned to this mission."""
    safe = _safe_mission_id(mission_id)
    dest = Path(folder) if folder is not None else Path("data/after_action") / safe
    dest.mkdir(parents=True, exist_ok=True)
    collected = _collect(list(asset_ids or []))
    generation = uuid4().hex
    relative = Path("generations") / generation
    published = dest / relative
    published.parent.mkdir(exist_ok=True)
    entries = {name: (relative / f"{name}.parquet").as_posix() for name in TABLES}
    files = {name: str(dest / entry) for name, entry in entries.items()}
    manifest = {
        "version": 1,
        "generation": generation,
        "mission_id": mission_id,
        "files": entries,
        "row_counts": {name: len(collected[name]) for name in TABLES},
    }
    with TemporaryDirectory(dir=dest, prefix=".export-") as temporary:
        staging = Path(temporary)
        archive = staging / "archive"
        archive.mkdir()
        for name in TABLES:
            path = archive / f"{name}.parquet"
            frame = _frame(mission_id, name, collected[name])
            if name == "events":
                table = frame.to_arrow()
                metadata = dict(table.schema.metadata or {})
                metadata.update({
                    b"samanvaya.archive.schema": b"events.v1",
                    b"samanvaya.archive.mission_id_source": b"export_request",
                    b"samanvaya.archive.selection": b"asset_id",
                })
                pq.write_table(table.replace_schema_metadata(metadata), path, compression="zstd")
            else:
                frame.write_parquet(path)
        descriptor = archive / "manifest.json"
        descriptor.write_text(json.dumps(manifest), encoding="utf-8")
        # Legacy paths remain independently writable without changing a pinned generation.
        for name in TABLES:
            shutil.copyfile(archive / f"{name}.parquet", staging / f"{name}.parquet")
        shutil.copyfile(descriptor, staging / "manifest.json")
        archive.rename(published)
        for name in TABLES:
            (staging / f"{name}.parquet").replace(dest / f"{name}.parquet")
        (staging / "manifest.json").replace(dest / "manifest.json")
    try:
        upload_status = _upload(files, safe, published / "manifest.json", relative)
    except Exception:
        upload_status = "failed"
    return {
        "mission_id": mission_id,
        "folder": str(dest),
        "generation": generation,
        "manifest": str(published / "manifest.json"),
        "files": files,
        "uploaded": upload_status == "uploaded",
        "upload_status": upload_status,
    }
