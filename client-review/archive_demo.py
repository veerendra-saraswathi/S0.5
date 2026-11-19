"""Run from the repository checkout with its Python dependencies installed."""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="Verify two local archive generations.")
    parser.add_argument("--json", action="store_true", help="print the verified result as JSON")
    args = parser.parse_args()
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
        initial = read_events(first["manifest"])
        second = publish("sample-B")
        old = read_events(first["manifest"])
        latest = read_events(dest / "manifest.json")
        current = json.loads((dest / "manifest.json").read_text())
        if first["generation"] == second["generation"] or current["generation"] != second["generation"]:
            raise RuntimeError("Current manifest does not identify a distinct second generation")
        if initial != ["sample-A"] or old != initial or latest != ["sample-A", "sample-B"]:
            raise RuntimeError("Archive event check failed")
        if args.json:
            print(json.dumps({
                "verified": True,
                "first": {"generation": first["generation"], "events": initial,
                          "upload_status": first["upload_status"]},
                "current": {"generation": current["generation"], "events": latest,
                            "upload_status": second["upload_status"]},
                "first_reopened_events": old,
            }))
            return
        print("First export:", first["generation"], initial)
        print("Second export:", second["generation"], latest)
        print("First export reopened:", old)
        print("MinIO upload status:", second["upload_status"])
        print("Verified: the first export still contains exactly its original event.")


if __name__ == "__main__":
    main()
