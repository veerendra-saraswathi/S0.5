# Samanvaya 0.5

EGurukulApps is developing Samanvaya 0.5 for Problem 7, a unified operator interface for heterogeneous assets. The simulation proof of concept brought two UAVs and two UGVs onto one dashboard. The team is preparing the MVP for a witnessed review.

## Client review

| Start here | What you can do |
|---|---|
| [MVP review deck](client-review/Samanvaya_05_MVP_Review.pptx) · [PDF](client-review/Samanvaya_05_MVP_Review.pdf) | Review the scope, historical results, archive tests and proposed acceptance decisions. |
| [Offline fleet viewer](client-review/Recorded_Fleet_Review.html) | Download and open the HTML file in a browser. Expand the recorded runs to compare the fleet labels and outcomes. |
| [Eight-minute walkthrough](client-review/Presenter_Guide.md) | Rehearse the evidence review and run a live local archive demonstration. |
| [Problem 7 delivery tracker](docs/PROBLEM_7_PROGRESS.md) | Inspect completion evidence and remaining handover items. |

## Evidence at 20 November 2026

| Evidence | Result | Scope |
|---|---|---|
| [M5](docs/acceptance_m5.json) | 4/4 | Historical in-process simulation on a clean revision |
| [M7](docs/acceptance_m7.json) | 2/4 | Historical software-in-the-loop fleet profile with local changes |
| [Candidate ac87a6c](docs/fleet_dashboard_regression_20261119_ac87a6c.json) | 4/4 regression checks | Fleet configuration, adapter identity and telemetry, opening dashboard labels and a subsequent WebSocket frame |

A comparable four-criterion acceptance result for candidate `ac87a6c` remains outstanding. The team's approximate 65% MVP capability estimate is an internal planning judgment.

## Engineering references

- [Requirements trace](docs/EOI_TRACE.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Data and archive design](docs/ARCHITECTURE_DATA.md)
- [Historical test report](docs/TEST_REPORT.md)

To summarize the saved reports from the repository root, run `python3 scripts/evaluate_progress.py`.
