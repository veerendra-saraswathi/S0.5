"""Summarize saved Problem 7 acceptance evidence without starting services."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRITERIA = ("10.1", "10.2", "10.3", "10.4")


def summarize_acceptance(path, report):
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

    return git.get("commit")


def summarize_regression(path, report):
    commit = report["commit"]
    if not isinstance(commit, str) or not commit.strip():
        raise ValueError("missing regression commit")
    tests = report["tests"]
    if not isinstance(tests, list) or not tests:
        raise ValueError("expected a nonempty test list")
    names = set()
    passed = 0
    for test in tests:
        name = test["name"]
        if not name or name in names or test["result"] not in ("passed", "failed", "skipped", "error"):
            raise ValueError(f"invalid or duplicate regression test {name}")
        names.add(name)
        passed += test["result"] == "passed"
    print(f"{path.name} | {passed}/{len(tests)} regression checks passed | commit: {commit}")
    return commit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    docs = ROOT / "docs"
    defaults = [docs / f"acceptance_{name}.json" for name in ("m5", "m7")]
    defaults.extend(sorted(docs.glob("fleet_dashboard_regression_*.json")))
    parser.add_argument("reports", nargs="*", type=Path, default=defaults)
    acceptance_commits = set()
    regression_commits = set()
    for path in parser.parse_args().reports:
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
            if "criteria" in report:
                acceptance_commits.add(summarize_acceptance(path, report))
            elif "tests" in report:
                regression_commits.add(summarize_regression(path, report))
            else:
                raise ValueError("expected acceptance criteria or regression tests")
        except (OSError, KeyError, ValueError, TypeError, AttributeError) as exc:
            parser.exit(2, f"{path}: {exc}\n")
    for commit in sorted(regression_commits - acceptance_commits):
        print(f"{commit[:7]} | no acceptance report for this commit among the selected files")


if __name__ == "__main__":
    main()
