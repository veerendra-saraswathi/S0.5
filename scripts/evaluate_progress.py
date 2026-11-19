"""Summarize saved Problem 7 acceptance evidence without starting services."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRITERIA = ("10.1", "10.2", "10.3", "10.4")


def summarize(path):
    report = json.loads(path.read_text(encoding="utf-8"))
    results = {}
    for row in report["criteria"]:
        key = row["id"]
        if key in results or type(row["pass"]) is not bool:
            raise ValueError(f"invalid or duplicate criterion {key}")
        results[key] = row["pass"]
    env = report.get("environment", {})
    git = env.get("git", {})
    passed = sum(results.get(key) is True for key in CRITERIA)
    detail = ", ".join(
        f"{key} " + ({True: "PASS", False: "FAIL"}.get(results.get(key), "MISSING"))
        for key in CRITERIA
    )
    print(f"{path.name} | {report.get('started_at', 'undated')} | {passed}/4 passed")
    print(f"  {detail}")
    print(f"  Profile: {env.get('radio_path', 'unknown')} | commit: {git.get('commit', 'unknown')}")
    print(f"  Completed: {report.get('completed')} | reportable: {env.get('reportable')} | dirty: {git.get('dirty')}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="*", type=Path,
                        default=[ROOT / "docs" / f"acceptance_{name}.json" for name in ("m5", "m7")])
    for path in parser.parse_args().reports:
        try:
            summarize(path)
        except (OSError, KeyError, ValueError, TypeError) as exc:
            parser.exit(2, f"{path}: {exc}\n")


if __name__ == "__main__":
    main()
