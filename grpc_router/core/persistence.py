"""Write-behind persistence of the service register to a local JSON file.

The file is human readable, e.g.::

    {
      "version": 1,
      "saved_at": "2026-11-27T12:00:00.000000+00:00",
      "instances": [
        {"service_id": "myorg.billing.invoices", "host": "invoices1", "port": 8080, "region": "us-east",
         "slots": 10, "health_check_type": "ACTIVE_CLIENT", "service_token": "...", "in_service": true,
         "health_status": "GOOD", "description": ""}
      ]
    }

Changes are saved by a background thread, at most once per save interval, so a crash can
lose the changes of the last interval; services recover from that themselves by
registering again when the router answers NOT_FOUND to their heartbeats. The file holds
the service tokens, which act as credentials, so it is only readable by its owner.
"""

import datetime
import json
import logging
import os
import tempfile
import threading
from pathlib import Path

from grpc_router.core.register import ServiceRegister

logger = logging.getLogger(__name__)

STATE_FORMAT_VERSION = 1


class StateFileError(Exception):
    pass


def save_state(path: Path, register: ServiceRegister) -> None:
    """Atomically write the register to path (temporary file in the same directory + rename)."""
    state = {
        "version": STATE_FORMAT_VERSION,
        "saved_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "instances": register.snapshot(),
    }
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")  # mode 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def load_state(path: Path, register: ServiceRegister) -> None:
    """Restore the register from path if it exists.

    A file that cannot be read is moved aside (to <name>.bad-<timestamp>) and the router
    starts empty: services register again on their own.
    """
    if not path.exists():
        logger.info("No state file at %s, starting with an empty register", path)
        return
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if state.get("version") != STATE_FORMAT_VERSION:
            raise StateFileError(f"unsupported state file version {state.get('version')!r}")
        saved_at = datetime.datetime.fromisoformat(state["saved_at"])
        register.restore(state["instances"])
    except Exception as exc:
        bad = path.with_name(f"{path.name}.bad-{datetime.datetime.now(datetime.UTC):%Y%m%dT%H%M%SZ}")
        os.replace(path, bad)
        logger.error("Could not load the state file %s (%s); moved it to %s and starting empty", path, exc, bad)
        return
    instances = state["instances"]
    out_of_service = sum(1 for data in instances if not data["in_service"])
    age = datetime.datetime.now(datetime.UTC) - saved_at
    logger.info(
        "Restored %d service instances (%d out of service) from %s, saved at %s (%ds ago)",
        len(instances), out_of_service, path, saved_at.isoformat(), age.total_seconds(),
    )


class StateWriter:
    """Saves the register to a file in the background whenever it changes."""

    def __init__(self, path: Path, register: ServiceRegister, save_interval: float) -> None:
        self._path = path
        self._register = register
        self._save_interval = save_interval
        self._dirty = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Load the state, save it once (so an unwritable path fails now, not later), then
        save in the background on every change."""
        load_state(self._path, self._register)
        save_state(self._path, self._register)
        self._register.on_change = self._dirty.set
        self._thread = threading.Thread(target=self._run, name="grpc-router-state-writer", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._dirty.wait()
            if self._stop.is_set():
                break
            self._dirty.clear()
            self._save()
            # write behind: coalesce the changes of the next interval into one save
            self._stop.wait(self._save_interval)

    def _save(self) -> None:
        try:
            save_state(self._path, self._register)
        except Exception:
            logger.exception("Could not save the state file %s; will retry on the next change", self._path)
            self._dirty.set()

    def stop(self) -> None:
        """Stop the background thread and save any pending change."""
        if self._thread is None:
            return
        self._stop.set()
        self._dirty.set()
        self._thread.join()
        self._thread = None
        self._register.on_change = None
        save_state(self._path, self._register)
