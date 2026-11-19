# Problem 7 delivery tracker

Baseline reviewed 19 November 2026 at de3d496. PoC demonstrated in simulation.
MVP capability estimate approximately 65%, by engineering judgment. Formal acceptance pending.
The estimate applies to S0.5. S1, S2 and S3 have separate scopes.

Run `python3 scripts/evaluate_progress.py` for the two reference acceptance runs and saved fleet dashboard regression reports. Pass one or more
report paths to evaluate subsequent runs. Compare like profiles. Record the commit,
worktree state, configuration and date for every run. Inspect missing criteria,
incomplete runs and the reportable flag before using a result for a milestone.

| Final delivery item | Evidence already available | Evidence still needed for closure |
|---|---|---|
| Integrated software and seven-layer design | Repository layout and EOI trace | Release design and a clause-to-evidence index covering every layer |
| Four heterogeneous assets and extensible adapters | M5 simulation passed 10.1; later M7 run failed it | Repeatable release result for the agreed real, simulated or hybrid configuration and documented adapter interfaces |
| Communication, asset status and cross-asset information exchange | Both reference runs passed 10.2 | Recorded release run and configuration, including agreed communication and recovery checks |
| Single operator interface, platform control and common picture | Both runs passed 10.4; mixed evidence for 10.3 | Same release demonstrates both criteria and the required displays and alerts |
| Data services, security and audit | Archive snapshot consistency verified on DuckDB and PostgreSQL. See the 19 November validation below | Evidence for access control, attribution, persistence and recovery in the release configuration |
| Deployment and equipment | Local development configuration and simulation fleet | Reproducible installation, dependencies and agreed equipment inventory |
| Handover and acceptance | Source, adapters, architecture notes and historical test reports | Release source, design, operator and administrator manuals, final test report, demonstration and acceptance record |

Update this table when a deliverable is verified. Record the evidence path and release
commit. Revisit the estimate after a comparable acceptance run or delivery milestone.
The signed SoW and agreed acceptance configuration govern the final checklist.

## Archive validation on 19 November 2026

Candidate commit `ac87a6c`. The DuckDB and PostgreSQL cases of
`test_archive_collection_pins_one_source_snapshot` in
`src/data_services/test_repositories.py` passed. Both cases check that an event
and an alert committed halfway through collection appear only in the next export.

The PostgreSQL result comes from the developer's local terminal run. A disposable
`timescale/timescaledb-ha:pg16` instance applied migrations through
`0003_snapshot_and_command_status`. Pytest reported 1 passed in 3.37 seconds.
The image digest was `sha256:5d1a6980aa255b5035e24e0de6808c134bf2bf19cf551571acbd092ad38a4b8d`.

A fresh four-asset acceptance result for this candidate remains pending.

## MinIO archive readback on 20 November 2026

At commit `f9d7e29`, the developer ran
`src/data/test_minio_readback.py::test_read_published_generation` against a
disposable local MinIO server. Pytest reported **1 passed in 9.78 seconds**.
The reader downloaded the published manifest and all four Parquet files for
its generation. Every downloaded file matched the corresponding local file
byte for byte. The export contained zero data rows.

The Intel Mac ran the linux/amd64 image from the unofficial `jcometki/minio`
mirror, pinned to digest
`sha256:a1ea29fa28355559ef137d71fc570e508a214ec84ff8083e39bc5428980b015e`.

At `77e72c4`, the two-export MinIO test passed in **5.83 seconds** on the
developer's Mac. The current manifest identified the second generation. The
reader then reopened the first generation by ID and verified the manifest and
all four original Parquet files byte for byte. Both exports contained zero data
rows. The four-asset acceptance status is unchanged.
