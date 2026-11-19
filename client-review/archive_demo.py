"""Run from the repository checkout with its Python dependencies installed."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def main():
    with TemporaryDirectory(prefix="s05-client-review-") as work:
        os.environ.update(STORAGE_BACKEND="duckdb", CNC_DUCKDB_PATH=str(Path(work) / "review.duckdb"),
                          MINIO_ENDPOINT="")
        sys.path.insert(0, str(ROOT))
        import polars as pl
        from src.data.after_action import write_after_action
        from src.data_services.repositories import get_repositories

        repo = get_repositories()
        dest = Path(work) / "exports"
        def publish(label):
            repo.events.insert(label, datetime.now(timezone.utc), "review", label,
                               "sample-01", "info", {"source": "client-demo"})
            return write_after_action("review", ["sample-01"], dest)

        def read_events(manifest):
            record = json.loads(Path(manifest).read_text())
            frame = pl.read_parquet(dest / record["files"]["events"])
            return sorted(frame["event_id"].to_list())

        first = publish("sample-A")
        print("First export:", first["generation"], read_events(first["manifest"]))
        second = publish("sample-B")
        old = read_events(first["manifest"])
        latest = read_events(dest / "manifest.json")
        print("Second export:", second["generation"], latest)
        print("First export reopened:", old)
        if old != ["sample-A"] or latest != ["sample-A", "sample-B"]:
            raise RuntimeError("Archive generation check failed")
        print("Verified: the first export still contains exactly its original event.")


if __name__ == "__main__":
    main()
