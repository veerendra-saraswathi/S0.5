# Samanvaya 0.5 client walkthrough

**Meeting objective.** Show what has been demonstrated and agree on the profile, evidence and owner for the next witnessed acceptance review. Allow eight minutes for the walkthrough and five for questions.

## Before the meeting

Download the [PowerPoint](Samanvaya_05_MVP_Review.pptx), [PDF](Samanvaya_05_MVP_Review.pdf) and [fleet viewer](Recorded_Fleet_Review.html). Open the HTML locally in a browser. GitHub previews its source. The deck, PDF and viewer work offline. For the live archive segment, use the repository checkout and its Python environment with DuckDB, PyArrow and Polars installed. Rehearse once on the presentation machine.

## Presentation sequence

| Time | Screen | What to show or say |
|---|---|---|
| 0:00–1:00 | Slides 1–2 | “Our simulation PoC brought four assets onto one dashboard. Today we will show the recorded results and create a new sample archive.” |
| 1:00–3:00 | Slide 3 and fleet viewer | Expand M5 and M7. Point out that M5 passed four criteria. In M7 the opening inventory labeled both UAVs “other”; the overall integration and platform-control checks failed. Explain that the profiles and revisions differ. |
| 3:00–4:00 | Candidate panel and slide 4 | Expand ac87a6c. Four separate regression checks passed. Explicitly identify the fresh end-to-end acceptance run as pending. |
| 4:00–6:00 | Terminal and slide 5 | Run the archive demo below. Show the two generation IDs and reopen the first export after the second is published. |
| 6:00–8:00 | Slide 6 | Ask which profile the client wants to witness, which records they require and who should review the evidence. Capture the decisions and a proposed date. |

## Live archive demo

From the repository root, using the project's Python environment:

```sh
python client-review/archive_demo.py
```

The script creates a temporary DuckDB database, inserts two labeled sample events and calls the repository's Parquet exporter twice. It opens the first manifest again and checks that it still returns only `sample-A`. The latest manifest must return both `sample-A` and `sample-B`. Generation identifiers vary on each run. The script disables MinIO upload, uses no client records, and removes its temporary database and files when it exits.

If the environment is unavailable, use the PDF and offline viewer and describe the archive segment as a previously rehearsed demonstration. For the remote storage result, say “After a second export became current, we reopened the first by its generation ID on live MinIO and verified all four original files byte for byte. The current export contained events A and B. The first export still contained only event A.” The [tracker](../docs/PROBLEM_7_PROGRESS.md) records the test revision and result.

## Questions to settle before acceptance

1. Which profile and release commit should the client witness?
2. Which run records, manuals and deployment details will the reviewer retain?
3. Who will review the result and agree the next date?

The approximate 65% figure expresses the team's judgment of MVP capability delivered. Formal acceptance remains open. S1, S2 and S3 belong to separate delivery scopes.
