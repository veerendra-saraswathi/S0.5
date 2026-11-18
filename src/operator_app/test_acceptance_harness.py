"""Stop deadline and dashboard delta merge. No Docker daemon required."""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import acceptance_run  # noqa: E402


def test_run_cmd_kills_a_hung_child():
    started = time.monotonic()
    proc = acceptance_run.run_cmd(["sleep", "30"], timeout=0.4)
    elapsed = time.monotonic() - started
    assert elapsed < 2.0
    assert proc.returncode != 0


def test_active_start_body_passes_without_a_fetch():
    assert acceptance_run.mission_start_ok(
        hold_acked=True,
        hold_actor="operator:op-1",
        hold_has_events=True,
        mission_code=200,
        start_code=200,
        start_body={"status": "active", "started_at": "t"},
        fetched=None,
        mission_commands=[],
        assigned=["uav-01"],
        actor="operator:op-1",
    )


def test_timeout_passes_when_the_store_has_the_mission_commands():
    assigned = ["uav-01", "uav-02", "ugv-01", "ugv-02"]
    commands = [
        {"asset_id": asset_id, "issued_by": "mission", "command_type": "goto"}
        for asset_id in assigned
    ]
    assert acceptance_run.mission_start_ok(
        hold_acked=True,
        hold_actor="operator:op-1",
        hold_has_events=True,
        mission_code=200,
        start_code=0,
        start_body=None,
        fetched={"status": "active", "started_at": "t"},
        mission_commands=commands,
        assigned=assigned,
        actor="operator:op-1",
    )


def test_timeout_fails_without_a_mission_command():
    assert not acceptance_run.mission_start_ok(
        hold_acked=True,
        hold_actor="operator:op-1",
        hold_has_events=True,
        mission_code=200,
        start_code=0,
        start_body=None,
        fetched={"status": "active", "started_at": "t"},
        mission_commands=[],
        assigned=["uav-01", "ugv-01"],
        actor="operator:op-1",
    )


def test_a_second_peer_fails_the_single_socket_check():
    assert acceptance_run.socket_is_single(["127.0.0.1:1"])
    assert not acceptance_run.socket_is_single(["127.0.0.1:1", "127.0.0.1:2"])


def test_delta_merges_into_the_last_snapshot():
    latest = {
        "type": "snapshot",
        "assets": [
            {"id": "uav-01", "alt": 10, "name": "Eagle-1"},
            {"id": "ugv-01", "alt": 0, "name": "Rover-1"},
        ],
        "alerts": [{"id": "a1", "title": "old"}],
    }
    merged = acceptance_run._merge_frame(latest, {
        "type": "delta",
        "timestamp": "t",
        "assets": [{"id": "uav-01", "alt": 80}],
    })
    by_id = {row["id"]: row for row in merged["assets"]}
    assert by_id["uav-01"]["alt"] == 80
    assert by_id["uav-01"]["name"] == "Eagle-1"
    assert by_id["ugv-01"]["alt"] == 0
    assert merged["alerts"][0]["id"] == "a1"
    replaced = acceptance_run._merge_frame(latest, {"type": "snapshot", "assets": []})
    assert replaced["assets"] == []
