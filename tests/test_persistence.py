import json
import logging
import signal
import stat
import subprocess
import sys
import time

import grpc
import pytest

from grpc_router.client.client import GRPCRouterClient
from grpc_router.core.models import ConfigOptions, HealthCheckType, HealthStatus
from grpc_router.core.persistence import StateWriter, load_state, save_state
from grpc_router.core.register import ServiceRegister
from grpc_router.stubs.grpc_router_service_pb2 import HEALTH_STATUS_GOOD, HealthInfoRequest

CONFIG = ConfigOptions(hostname="localhost", port=0, max_workers=1)


def _register_with_instances() -> tuple[ServiceRegister, list[str]]:
    register = ServiceRegister(CONFIG)
    tokens = [
        register.register_service("svc", host, 1234, region, 10, HealthCheckType.ACTIVE_CLIENT)[0]
        for host, region in (("a", "east"), ("b", "west"), ("c", ""))
    ]
    register.push_health_status("svc", tokens[1], HealthStatus.ERROR, "db down")
    return register, tokens


def test_state_file_round_trip(tmp_path):
    path = tmp_path / "state.json"
    register, tokens = _register_with_instances()
    save_state(path, register)

    # readable JSON, with the time of the save, only readable by its owner (it holds tokens)
    state = json.loads(path.read_text())
    assert state["version"] == 1
    assert state["saved_at"].endswith("+00:00")
    assert {i["host"]: (i["in_service"], i["health_status"], i["description"]) for i in state["instances"]} == {
        "a": (True, "GOOD", ""), "b": (False, "ERROR", "db down"), "c": (True, "GOOD", ""),
    }
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    restored = ServiceRegister(CONFIG)
    load_state(path, restored)
    assert restored.snapshot() == register.snapshot()
    assert restored.get_service("svc", "east").host == "a"
    assert restored.push_health_status("svc", tokens[1], HealthStatus.GOOD, "").host == "b"


def test_missing_state_file_starts_empty(tmp_path):
    register = ServiceRegister(CONFIG)
    load_state(tmp_path / "state.json", register)
    assert register.snapshot() == []


@pytest.mark.parametrize("content", [
    "{not json",
    '{"version": 99, "saved_at": "2026-01-01T00:00:00+00:00", "instances": []}',
    '{"version": 1, "saved_at": "2026-01-01T00:00:00+00:00", "instances": [{"host": "a"}]}',
])
def test_unreadable_state_file_is_moved_aside(tmp_path, caplog, content):
    path = tmp_path / "state.json"
    path.write_text(content)
    register = ServiceRegister(CONFIG)
    with caplog.at_level(logging.ERROR):
        load_state(path, register)
    assert register.snapshot() == []
    assert not path.exists()
    [bad] = tmp_path.glob("state.json.bad-*")
    assert bad.read_text() == content  # kept for inspection, not overwritten by the next save
    assert "Could not load the state file" in caplog.text


def _saved_at(path) -> str:
    return json.loads(path.read_text())["saved_at"]


def test_state_writer_writes_behind(tmp_path):
    path = tmp_path / "state.json"
    register = ServiceRegister(CONFIG)
    writer = StateWriter(path, register, save_interval=0.1)
    writer.start()
    try:
        assert json.loads(path.read_text())["instances"] == []  # saved once at start

        token, _ = register.register_service("svc", "a", 1234, "", 10, HealthCheckType.ACTIVE_CLIENT)
        deadline = time.monotonic() + 5
        while not json.loads(path.read_text())["instances"] and time.monotonic() < deadline:
            time.sleep(0.05)
        assert [i["service_token"] for i in json.loads(path.read_text())["instances"]] == [token]

        # plain heartbeats do not rewrite the file
        saved_at = _saved_at(path)
        for _ in range(3):
            register.push_health_status("svc", token, HealthStatus.GOOD, "")
            time.sleep(0.1)
        assert _saved_at(path) == saved_at
    finally:
        writer.stop()
    assert _saved_at(path) > saved_at  # final save on stop
    assert not list(tmp_path.glob(".state.json.*"))  # no temporary files left behind


def test_state_writer_fails_fast_on_unwritable_path(tmp_path):
    writer = StateWriter(tmp_path / "missing-dir" / "state.json", ServiceRegister(CONFIG), save_interval=1)
    with pytest.raises(FileNotFoundError):
        writer.start()


# --- end to end: a router process with a state file, restarted ----------------------

PORT = 7658


def _start_router(state_file) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "grpc_router.server", "-n", "localhost", "-p", str(PORT),
         "--state-file", str(state_file), "--shutdown-grace", "0"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    with grpc.insecure_channel(f"localhost:{PORT}") as channel:
        grpc.channel_ready_future(channel).result(timeout=10)
    return proc


def _stop_router(proc: subprocess.Popen) -> str:
    proc.send_signal(signal.SIGTERM)
    output, _ = proc.communicate(timeout=10)
    assert proc.returncode == 0, output
    return output


def test_router_restart_with_state_file(tmp_path):
    state_file = tmp_path / "state.json"
    proc = _start_router(state_file)
    try:
        service = GRPCRouterClient("localhost", PORT)
        token = service.register_service("persisted.active", "active.mydomain.com", 4401, "", 10,
                                         HealthCheckType.ACTIVE_CLIENT)
        # services without health checks never re-register: only the state file brings them back
        service.register_service("persisted.none", "none.mydomain.com", 4402)
        service.close()
        _stop_router(proc)  # graceful: the final save happens even within the save interval

        proc = _start_router(state_file)
        with GRPCRouterClient("localhost", PORT) as client:
            # known straight away, before any heartbeat
            assert client.get_service("persisted.active") == ("active.mydomain.com", 4401)
            assert client.get_service("persisted.none") == ("none.mydomain.com", 4402)
            # and the old token still works for heartbeats
            client.stub.PushHealthStatus(HealthInfoRequest(
                service_id="persisted.active", service_token=token, status=HEALTH_STATUS_GOOD))
        output = _stop_router(proc)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()
    assert "Restored 2 service instances (0 out of service)" in output


def test_state_writer_retries_after_a_failed_save(tmp_path, monkeypatch, caplog):
    # e.g. a full disk for a moment: the writer keeps going and saves on a later attempt
    from grpc_router.core import persistence

    path = tmp_path / "state.json"
    register = ServiceRegister(CONFIG)
    writer = StateWriter(path, register, save_interval=0.05)
    writer.start()
    real_save, failures = persistence.save_state, []

    def flaky_save(*args):
        if not failures:
            failures.append(1)
            raise OSError("No space left on device")
        real_save(*args)

    monkeypatch.setattr(persistence, "save_state", flaky_save)
    try:
        register.register_service("svc", "a", 1234, "", 10, HealthCheckType.NONE)
        deadline = time.monotonic() + 5
        while not json.loads(path.read_text())["instances"] and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(json.loads(path.read_text())["instances"]) == 1
    finally:
        writer.stop()
    assert failures and "Could not save the state file" in caplog.text
