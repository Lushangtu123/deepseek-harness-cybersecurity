#!/usr/bin/env python3
"""Identity-checked resource ownership for the CLI experiment.

This module is deliberately smaller than the experiment runner.  It owns the
only sanctioned ways to create, query, stop and remove the resources that a
preflight, a preparation step or an attempt can allocate:

* a Docker container is addressed by its **full ID** after creation; its exact
  name, ``sce.tag`` label and fixed image are verified before any removal, and
  absence is confirmed with three successful queries (full ID, exact name and
  ownership-tag listing);
* a process group is addressed by ``(pgid, leader starttime, boot id)``.  A
  missing identity, an unreadable or malformed ``/proc`` entry, a changed
  starttime or an orphaned group is ``unknown`` and is never reported exited;
* a stage directory is addressed by ``(dev, ino)`` from ``lstat``; symlinks,
  replaced directories and unreadable parents are never followed or removed.

Nothing in this module writes an experiment receipt.  Callers persist intent
before invoking a create/spawn operation and persist the new identity after it.
"""
import errno
import fcntl
import hashlib
import json
import os
import re
import select
import shutil
import signal
import stat
import subprocess
import threading
import time
from pathlib import Path

FIXED_IMAGE = "sha256:9479bc40712c72437ee2630d947c102cf0c1cd5200ec038026272427925b82e7"
HASH_RE = re.compile(r"[a-f0-9]{64}")
ID_RE = re.compile(r"[a-f0-9]{12,64}")
FULL_ID_RE = re.compile(r"[a-f0-9]{64}")
PROC_STATES = frozenset("RSDZTtXxKWP?I")


# --------------------------------------------------------------------- digests
def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def digest(value):
    return sha_bytes(canonical(value))


def read_json(path):
    with open(path, "rb") as handle:
        raw = handle.read()
    return json.loads(raw), sha_bytes(raw)


def json_bytes(value):
    return json.dumps(value, sort_keys=True, indent=1).encode("utf-8") + b"\n"


def _fsync_directory(path):
    try:
        directory = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def atomic_write_bytes(path, payload):
    """Write bytes atomically (unique temp name) and return their digest."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-%d-%d" % (os.getpid(), time.monotonic_ns()))
    with open(temporary, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)
    return sha_bytes(payload)


def write_new_bytes(path, payload):
    """Create a new evidence file exactly once; never overwrite an old one."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    _fsync_directory(path.parent)
    return sha_bytes(payload)


def write_new_json_document(path, value):
    return value, write_new_bytes(path, json_bytes(value))


def write_new_or_identical(path, payload):
    """Create once, or reuse a byte-identical existing file without rewriting."""
    path = Path(path)
    state = path_state(path)
    if state["state"] == "present":
        if state["symlink"] or not state["isFile"]:
            return None, "not-regular"
        with open(path, "rb") as handle:
            existing = handle.read()
        if existing != payload:
            return None, "bytes-differ"
        return sha_bytes(existing), "reused"
    if state["state"] == "unknown":
        return None, "lstat"
    return write_new_bytes(path, payload), "created"


def write_json_document(path, value):
    """Write the exact bytes used for later file-byte digests.

    Returns ``(value, sha256_of_written_bytes)``.  This is intentionally *not*
    a canonical-JSON digest: all cross-receipt links use the bytes at rest.
    Used for mutable lifecycle state, never for one-time evidence.
    """
    payload = json_bytes(value)
    return value, atomic_write_bytes(path, payload)


# ------------------------------------------------------------------ stable lock
class ExclusiveLock:
    """One stable, never-unlinked lock file for a protected operation."""

    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # The lock inode is stable: we never unlink or replace this file.
        handle = open(self.path, "a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            if error.errno in (errno.EACCES, errno.EAGAIN):
                return False
            raise
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({"pid": os.getpid(), "acquiredAt": time.time()}) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        self.handle = handle
        return True

    def release(self):
        if self.handle is None:
            return
        try:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


# ---------------------------------------------------------------------- docker
def docker(*args, timeout=120):
    return subprocess.run(
        ["docker", *args], check=False, capture_output=True, text=True, timeout=timeout
    )


def classify_docker_error(stderr):
    text = (stderr or "").strip()
    if re.search(r"No such (object|container)", text, re.IGNORECASE):
        return "absent"
    if re.search(r"permission denied|Permission denied", text):
        return "unknown"
    if re.search(
        r"Cannot connect to the Docker daemon|Is the docker daemon running|"
        r"connection refused|dial unix",
        text,
        re.IGNORECASE,
    ):
        return "unknown"
    return "unknown"


def container_lookup(identifier):
    """Query a container by name or ID; returns absent/present/unknown."""
    if not isinstance(identifier, str) or not identifier:
        return {"state": "unknown", "detail": "empty-identifier"}
    try:
        result = docker("inspect", "--type", "container", "-f", "{{json .}}", identifier, timeout=60)
    except (OSError, subprocess.SubprocessError) as error:
        return {"state": "unknown", "detail": "query-error:" + type(error).__name__}
    if result.returncode != 0:
        classification = classify_docker_error(result.stderr)
        if classification == "absent":
            return {"state": "absent", "detail": "no-such-object"}
        return {"state": "unknown", "detail": "query:" + (result.stderr or "").strip()[:160]}
    try:
        value = json.loads(result.stdout or "{}")
    except ValueError:
        return {"state": "unknown", "detail": "inspect-json"}
    if type(value) is not dict:
        return {"state": "unknown", "detail": "inspect-shape"}
    return {"state": "present", "container": value}


def container_tag_lookup(tag):
    """Successful, empty ownership-tag query is the only ``absent`` result."""
    if not isinstance(tag, str) or not re.fullmatch(r"[a-f0-9]{16,64}", tag):
        return {"state": "unknown", "detail": "tag"}
    try:
        result = docker(
            "ps", "-a", "--filter", "label=sce.tag=" + tag,
            "--format", "{{.ID}} {{.Names}}", timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {"state": "unknown", "detail": "query-error:" + type(error).__name__}
    if result.returncode != 0:
        return {"state": "unknown", "detail": "query:" + (result.stderr or "").strip()[:160]}
    rows = [line for line in (result.stdout or "").splitlines() if line.strip()]
    if not rows:
        return {"state": "absent", "rows": []}
    return {"state": "present", "rows": rows}


def parse_container(raw):
    if type(raw) is not dict:
        return None
    config = raw.get("Config") if type(raw.get("Config")) is dict else {}
    state = raw.get("State") if type(raw.get("State")) is dict else {}
    labels = config.get("Labels") if type(config.get("Labels")) is dict else {}
    mounts = raw.get("Mounts") if type(raw.get("Mounts")) is list else []
    host = raw.get("HostConfig") if type(raw.get("HostConfig")) is dict else {}
    return {
        "id": raw.get("Id"),
        "name": (raw.get("Name") or "").lstrip("/"),
        "image": config.get("Image"),
        "user": config.get("User"),
        "entrypoint": config.get("Entrypoint"),
        "labels": labels,
        "status": state.get("Status"),
        "pid": state.get("Pid"),
        "mounts": mounts,
        "hostConfig": host,
    }


def container_identity_matches(observed, expected_id, expected_name, expected_tag,
                               expected_image=FIXED_IMAGE):
    """Exact full-ID, name, ownership tag and image match; no prefix shortcut."""
    if observed is None:
        return "inspect-shape"
    if type(expected_id) is not str or not FULL_ID_RE.fullmatch(expected_id):
        return "expected-id"
    if type(observed.get("id")) is not str or not FULL_ID_RE.fullmatch(observed["id"]):
        return "container-id"
    if observed["id"] != expected_id:
        return "container-id-mismatch"
    if observed.get("name") != expected_name:
        return "container-name-mismatch"
    if (observed.get("labels") or {}).get("sce.tag") != expected_tag:
        return "container-tag-mismatch"
    if observed.get("image") != expected_image:
        return "container-image-mismatch"
    return None


def container_absent_all(record):
    """Prove absence by three independent successful queries.

    ``absent`` is returned only when the full recorded ID, the exact recorded
    name and an ownership-tag listing all succeed and match nothing.  A query
    failure or a same-name/tag replacement is ``unknown``/``present`` and keeps
    the reservation.
    """
    identifier = record.get("containerId")
    name = record.get("containerName")
    tag = record.get("tag")
    if not isinstance(identifier, str) or not identifier:
        return {"state": "unknown", "detail": "missing-id", "queries": {}}
    if not isinstance(name, str) or not name:
        return {"state": "unknown", "detail": "missing-name", "queries": {}}
    by_id = container_lookup(identifier)
    by_name = container_lookup(name)
    by_tag = container_tag_lookup(tag)
    queries = {
        "id": by_id,
        "name": by_name,
        "tag": by_tag,
    }
    if by_id["state"] == "present":
        return {"state": "present", "detail": "id", "queries": queries}
    if by_name["state"] == "present":
        return {"state": "present", "detail": "name-replacement", "queries": queries}
    if by_tag["state"] == "present":
        return {"state": "present", "detail": "tag-replacement", "queries": queries}
    if by_id["state"] != "absent" or by_name["state"] != "absent" or by_tag["state"] != "absent":
        return {"state": "unknown", "detail": "query-failed", "queries": queries}
    return {"state": "absent", "detail": None, "queries": queries}


def verify_own_container_present(record):
    """Query the recorded full ID and require exact identity; never remove."""
    identifier = record.get("containerId")
    name = record.get("containerName")
    tag = record.get("tag")
    image = record.get("image") or FIXED_IMAGE
    if not identifier or not name or not tag:
        return {"state": "unknown", "detail": "incomplete-identity"}
    lookup = container_lookup(identifier)
    if lookup["state"] == "absent":
        # The recorded ID is gone but its name/tag might now belong to a foreign
        # container.  Only a successful triple-empty query proves absence.
        absent = container_absent_all(record)
        if absent["state"] == "absent":
            return {"state": "absent", "detail": "id-gone", "queries": absent["queries"]}
        return {"state": "unknown", "detail": "id-absent-" + str(absent.get("detail")),
                "queries": absent.get("queries")}
    if lookup["state"] != "present":
        return {"state": "unknown", "detail": lookup.get("detail")}
    observed = parse_container(lookup["container"])
    reason = container_identity_matches(observed, identifier, name, tag, image)
    if reason:
        return {"state": "unknown", "detail": reason, "observed": observed}
    return {"state": "present", "observed": observed}


def remove_container_verified(record):
    """Remove only a container whose full ID/name/tag/image all match.

    ``record`` has ``containerId``, ``containerName``, ``tag`` and
    ``containerCreated``.  A query failure, a same-name replacement, a tag
    replacement or an image mismatch is ``unknown`` and is never removed.
    """
    identifier = record.get("containerId")
    name = record.get("containerName")
    tag = record.get("tag")
    image = record.get("image") or FIXED_IMAGE
    created = record.get("containerCreated") is True
    if not created:
        # A creation attempt without a confirmed identity is not proof of
        # absence.  Query the planned name and tag; only triple-empty passes.
        probe = {"containerId": identifier or "0" * 64, "containerName": name, "tag": tag}
        if identifier and FULL_ID_RE.fullmatch(identifier):
            absent = container_absent_all(probe)
            if absent["state"] == "absent":
                return {"removed": True, "state": "never-created", "queries": absent["queries"]}
            return {"removed": False, "state": absent["state"],
                    "detail": "unexpected-container:" + str(absent.get("detail")),
                    "queries": absent.get("queries")}
        by_name = container_lookup(name) if name else {"state": "unknown", "detail": "no-name"}
        by_tag = container_tag_lookup(tag) if tag else {"state": "unknown", "detail": "no-tag"}
        if by_name["state"] == "absent" and by_tag["state"] == "absent":
            return {"removed": True, "state": "never-created",
                    "queries": {"name": by_name, "tag": by_tag}}
        return {"removed": False, "state": "unknown" if
                (by_name["state"] != "absent" or by_tag["state"] != "absent") else "present",
                "detail": "unexpected-container",
                "queries": {"name": by_name, "tag": by_tag}}
    if not identifier or not name or not tag:
        return {"removed": False, "state": "unknown", "detail": "incomplete-identity"}
    present = verify_own_container_present(record)
    if present["state"] == "absent":
        return {"removed": True, "state": "absent", "queries": present.get("queries")}
    if present["state"] != "present":
        return {"removed": False, "state": "unknown",
                "detail": present.get("detail"), "observed": present.get("observed")}
    observed = present["observed"]
    reason = container_identity_matches(observed, identifier, name, tag, image)
    if reason:
        return {"removed": False, "state": "identity-mismatch", "detail": reason}
    try:
        result = docker("rm", "-f", identifier, timeout=60)
    except (OSError, subprocess.SubprocessError) as error:
        return {"removed": False, "state": "unknown", "detail": "rm-error:" + type(error).__name__}
    if result.returncode != 0:
        return {"removed": False, "state": "unknown", "detail": "rm:" + (result.stderr or "").strip()[:160]}
    absent = container_absent_all(record)
    if absent["state"] == "absent":
        return {"removed": True, "state": "removed", "queries": absent["queries"]}
    return {"removed": False, "state": absent["state"],
            "detail": "still-present:" + str(absent.get("detail")),
            "queries": absent.get("queries")}


def image_id():
    result = docker("image", "inspect", "-f", "{{.Id}}", FIXED_IMAGE, timeout=60)
    return result.stdout.strip() if result.returncode == 0 else None


# --------------------------------------------------------------------- process
def boot_id():
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return None


def proc_stat(pid):
    """Read one ``/proc/<pid>/stat`` entry with explicit unknown states.

    ``None`` means the PID is absent (a successful negative lookup).  An
    unreadable entry raises ``OSError`` (permission, I/O) and a readable but
    malformed entry returns an explicit ``unknown`` record.  Neither may ever
    be treated as an exited process.
    """
    if type(pid) is not int or pid <= 0:
        return None
    try:
        raw = Path("/proc/%d/stat" % pid).read_text()
    except FileNotFoundError:
        return None
    except OSError:
        raise
    try:
        head, tail = raw.rsplit(")", 1)
        if "(" not in head or int(head.split("(", 1)[0].strip()) != pid:
            raise ValueError("stat-pid")
        fields = tail.split()
        if len(fields) < 20 or fields[0] not in PROC_STATES:
            raise ValueError("stat-shape")
        values = {
            "pid": pid,
            "state": fields[0],
            "ppid": int(fields[1]),
            "pgid": int(fields[2]),
            "session": int(fields[3]),
            "starttime": int(fields[19]),
        }
        if any(values[key] < 0 for key in ("ppid", "pgid", "session", "starttime")):
            raise ValueError("stat-range")
        values["unknown"] = False
        return values
    except (ValueError, IndexError):
        return {"pid": pid, "unknown": True, "reason": "proc-stat-malformed"}


def process_identity(pid):
    """Snapshot a process as (pid, pgid, starttime, boot id)."""
    if not isinstance(pid, int) or pid <= 0:
        return None
    current_boot = boot_id()
    if not current_boot:
        return None
    try:
        stat = proc_stat(pid)
    except OSError:
        return None
    if stat is None or stat.get("unknown"):
        return None
    return {
        "pid": pid,
        "pgid": stat["pgid"],
        "starttime": stat["starttime"],
        "bootId": current_boot,
        "groupLeader": stat["pid"] == stat["pgid"],
    }


def process_state(identity):
    """alive/exited/unknown for one exact process identity.

    ``exited`` requires a successful read proving the PID is absent or a
    zombie.  A permission error, malformed stat or changed starttime is
    ``unknown``/``reused`` and is never proof of exit.
    """
    if not isinstance(identity, dict):
        return {"state": "unknown", "detail": "identity-missing"}
    pid = identity.get("pid")
    if type(pid) is not int or pid <= 0:
        return {"state": "unknown", "detail": "pid"}
    if not isinstance(identity.get("bootId"), str) or not identity["bootId"]:
        return {"state": "unknown", "detail": "boot-id-missing"}
    if identity["bootId"] != boot_id():
        return {"state": "unknown", "detail": "boot-id-changed"}
    try:
        stat = proc_stat(pid)
    except OSError as error:
        return {"state": "unknown", "detail": "proc-unreadable:" + type(error).__name__}
    if stat is None:
        return {"state": "exited", "detail": "pid-absent"}
    if stat.get("unknown"):
        return {"state": "unknown", "detail": stat.get("reason")}
    if stat["starttime"] != identity.get("starttime"):
        return {"state": "reused", "detail": "starttime-changed"}
    if stat["state"] in {"Z", "X"}:
        return {"state": "exited", "detail": "zombie"}
    return {"state": "alive"}


def group_members(pgid):
    """Return ``(members, error)``; any unreadable/malformed entry is unknown."""
    members = []
    try:
        names = os.listdir("/proc")
    except OSError as error:
        return None, "proc-unreadable:" + type(error).__name__
    for name in names:
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            stat = proc_stat(pid)
        except OSError as error:
            return None, "proc-unreadable:%d:%s" % (pid, type(error).__name__)
        if stat is None:
            continue
        if stat.get("unknown"):
            return None, "proc-stat-malformed:%d" % pid
        if stat["pgid"] == pgid:
            members.append({
                "pid": stat["pid"],
                "pidState": stat["state"],
                "starttime": stat["starttime"],
                "session": stat["session"],
            })
    return members, None


def group_state(identity):
    """State of a verified process group; ambiguous groups are ``unknown``.

    ``exited`` is returned only after a successful scan of ``/proc`` shows no
    live member.  A missing identity is ``unknown``, never ``absent``.
    """
    if not isinstance(identity, dict):
        return {"state": "unknown", "detail": "identity-missing"}
    pgid = identity.get("pgid")
    leader = identity.get("pid")
    if not isinstance(pgid, int) or pgid <= 0:
        return {"state": "unknown", "detail": "pgid"}
    if not isinstance(leader, int) or leader <= 0:
        return {"state": "unknown", "detail": "pid"}
    if identity.get("groupLeader") is not True:
        return {"state": "unknown", "detail": "not-group-leader"}
    if not isinstance(identity.get("bootId"), str) or not identity["bootId"]:
        return {"state": "unknown", "detail": "boot-id-missing"}
    if identity["bootId"] != boot_id():
        return {"state": "unknown", "detail": "boot-id-changed"}
    members, error = group_members(pgid)
    if error:
        return {"state": "unknown", "detail": error}
    live = [item for item in members if item["pidState"] not in {"Z", "X"}]
    if not live:
        return {"state": "exited", "members": len(members), "proof": "empty-group-query"}
    leader_row = next((item for item in live if item["pid"] == leader), None)
    if leader_row is None:
        return {"state": "unknown", "detail": "orphaned-group", "members": len(live)}
    if leader_row["starttime"] != identity.get("starttime"):
        return {"state": "unknown", "detail": "leader-reused", "members": len(live)}
    return {"state": "alive", "members": len(live)}


def spawn_group_state(record):
    """Classify a persisted spawn record, never a bare boolean.

    States:
    * ``not-started`` -> exited with proof ``not-started``;
    * ``started`` with a verified identity -> re-query the group;
    * anything else (attempted spawn without identity, unreadable identity,
      persisted ``unknown``) -> ``unknown``.
    """
    if not isinstance(record, dict):
        return {"state": "unknown", "detail": "spawn-record-missing"}
    spawn_state = record.get("spawnState")
    if spawn_state == "not-started":
        return {"state": "exited", "proof": "not-started"}
    if spawn_state != "started":
        return {"state": "unknown", "detail": "spawn-state:" + str(spawn_state)}
    identity = record.get("identity")
    if not isinstance(identity, dict):
        return {"state": "unknown", "detail": "identity-missing-after-spawn"}
    state = group_state(identity)
    state["proof"] = "group-query"
    return state


def _wait_group(identity, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = group_state(identity)
        if state["state"] in {"exited", "unknown", "reused"}:
            return state
        time.sleep(0.05)
    return group_state(identity)


def stop_group(identity, graceful=5.0, term=2.0):
    """Stop a verified group: SIGINT, then SIGTERM, then SIGKILL.

    ``forced`` is true as soon as TERM/KILL is needed.  Callers that need
    graceful observer END evidence must treat ``forced`` as a blocked run.
    A reused leader, an orphaned group or an unreadable ``/proc`` leaves the
    resource unresolved and never reports success.
    """
    state = group_state(identity)
    if state["state"] == "exited":
        return {"stopped": True, "state": "exited", "forced": False,
                "signal": None, "proof": state.get("proof")}
    if state["state"] != "alive":
        return {"stopped": False, "state": state["state"], "forced": False,
                "detail": state.get("detail")}
    pgid = identity["pgid"]
    forced = False
    for sig, wait in ((signal.SIGINT, graceful), (signal.SIGTERM, term), (signal.SIGKILL, 2.0)):
        state = group_state(identity)
        if state["state"] == "exited":
            return {"stopped": True, "state": "exited", "forced": forced,
                    "signal": signal.Signals(sig).name, "proof": state.get("proof")}
        if state["state"] != "alive":
            return {"stopped": False, "state": state["state"], "forced": forced,
                    "detail": state.get("detail")}
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            pass
        except OSError as error:
            if error.errno == errno.ESRCH:
                pass
            else:
                return {"stopped": False, "state": "unknown", "forced": forced,
                        "detail": "kill:" + type(error).__name__}
        state = _wait_group(identity, wait)
        if state["state"] == "exited":
            return {"stopped": True, "state": "exited", "forced": forced,
                    "signal": signal.Signals(sig).name, "proof": state.get("proof")}
        if state["state"] != "alive":
            return {"stopped": False, "state": state["state"], "forced": forced,
                    "detail": state.get("detail")}
        if sig == signal.SIGINT:
            forced = True
    return {"stopped": False, "state": "alive", "forced": True, "detail": "still-running"}


# ------------------------------------------------------------------------ stage
def path_state(path):
    """One small tri-state path query shared by cleanup and recovery.

    Only ``FileNotFoundError`` means *absent*.  ``PermissionError``,
    ``NotADirectoryError`` and every other ``OSError`` mean *unknown*.  A
    symlink is *present* (and is reported as ``symlink``) but is never followed
    and never used as an absence proof.  This function does not call
    ``lexists``/``exists``/``is_dir``; those collapse lookup errors into a
    boolean and cannot distinguish "missing" from "unreadable".
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return {"state": "absent", "detail": "file-not-found"}
    except PermissionError:
        return {"state": "unknown", "detail": "permission-denied"}
    except NotADirectoryError:
        return {"state": "unknown", "detail": "not-a-directory"}
    except OSError as error:
        return {"state": "unknown", "detail": type(error).__name__}
    mode = info.st_mode
    return {
        "state": "present",
        "detail": "symlink" if stat.S_ISLNK(mode) else (
            "directory" if stat.S_ISDIR(mode) else (
                "regular" if stat.S_ISREG(mode) else "other")),
        "symlink": stat.S_ISLNK(mode),
        "isDir": stat.S_ISDIR(mode),
        "isFile": stat.S_ISREG(mode),
        "dev": info.st_dev,
        "ino": info.st_ino,
        "mode": stat.S_IMODE(mode),
    }


def stage_identity(path):
    """Snapshot a real directory, never following a symlink."""
    state = path_state(path)
    if state["state"] == "absent":
        return None
    if state["state"] == "unknown":
        return {"error": "lstat", "detail": state["detail"]}
    if state["symlink"]:
        return {"error": "symlink"}
    if not state["isDir"]:
        return {"error": "not-directory"}
    return {
        "dev": state["dev"],
        "ino": state["ino"],
        "mode": state["mode"],
        "path": str(path),
    }


def stage_matches(path, identity):
    if not isinstance(identity, dict) or "dev" not in identity or "ino" not in identity:
        return "identity-missing"
    state = path_state(path)
    if state["state"] == "absent":
        return "absent"
    if state["state"] == "unknown":
        return "lstat-error"
    if state["symlink"]:
        return "symlink"
    if not state["isDir"]:
        return "not-directory"
    if state["dev"] != identity["dev"] or state["ino"] != identity["ino"]:
        return "identity-changed"
    return None


def _tree_has_symlink(path):
    for root, directories, files in os.walk(path, followlinks=False):
        for name in list(directories) + list(files):
            if os.path.islink(os.path.join(root, name)):
                return True
    return False


def cleanup_stage(path, identity):
    """Remove a verified stage; a final lstat must prove the path is gone.

    A symlink, a replaced directory or a missing identity is *not* a successful
    cleanup and is never followed.  ``removed=True`` is returned only when the
    final tri-state query is ``absent``.  Callers must also have proved that
    every container and process resource is gone before calling this function.
    """
    if not path:
        return {"removed": True, "state": "never-created", "lstatAfter": "absent"}
    state = path_state(path)
    if state["state"] == "absent":
        return {"removed": True, "state": "absent", "lstatAfter": "absent"}
    if state["state"] == "unknown":
        return {"removed": False, "state": "lstat-error", "lstatAfter": "unknown",
                "detail": state["detail"]}
    if state["symlink"]:
        return {"removed": False, "state": "symlink", "lstatAfter": "present"}
    if (not isinstance(identity, dict) or identity.get("error")
            or "dev" not in identity or "ino" not in identity):
        return {"removed": False, "state": "identity-missing", "lstatAfter": "present"}
    match = stage_matches(path, identity)
    if match == "absent":
        return {"removed": True, "state": "absent", "lstatAfter": "absent"}
    if match:
        return {"removed": False, "state": match,
                "lstatAfter": "unknown" if match == "lstat-error" else "present"}
    if _tree_has_symlink(path):
        return {"removed": False, "state": "tree-symlink", "lstatAfter": "present"}
    try:
        for root, directories, files in os.walk(path, topdown=False, followlinks=False):
            for name in files:
                try:
                    os.chmod(os.path.join(root, name), 0o600)
                except OSError:
                    pass
            for name in directories:
                try:
                    os.chmod(os.path.join(root, name), 0o700)
                except OSError:
                    pass
        os.chmod(path, 0o700)

        def force(function, target, _exc):
            try:
                os.chmod(target, 0o700)
            except OSError:
                return
            try:
                function(target)
            except OSError:
                pass

        try:
            shutil.rmtree(path, onexc=force)
        except TypeError:  # Python < 3.12
            shutil.rmtree(path, onerror=force)
    except OSError as error:
        after = path_state(path)
        return {"removed": False, "state": "rmtree", "detail": type(error).__name__,
                "lstatAfter": after["state"] if after["state"] != "unknown" else "unknown"}
    after = path_state(path)
    if after["state"] == "absent":
        return {"removed": True, "state": "removed", "lstatAfter": "absent"}
    if after["state"] == "unknown":
        return {"removed": False, "state": "lstat-after", "lstatAfter": "unknown",
                "detail": after["detail"]}
    return {"removed": False, "state": "still-present", "lstatAfter": "present"}


# ----------------------------------------------------------------- stream drain
class StreamDrain:
    """Bounded, continuous consumer for a subprocess stream.

    The reader continues to drain after the cap so the child cannot block, but
    only the first ``limit`` bytes are retained.  ``truncated`` is sticky and
    ``completed`` is true only after EOF was observed by the reader thread.
    """

    def __init__(self, stream, limit):
        self.stream = stream
        self.limit = limit
        self.buffer = bytearray()
        self.truncated = False
        self.error = None
        self.completed = False
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            descriptor = self.stream.fileno()
            while True:
                chunk = os.read(descriptor, 65536)
                if not chunk:
                    self.completed = True
                    break
                with self._lock:
                    room = self.limit - len(self.buffer)
                    if room > 0:
                        self.buffer.extend(chunk[:room])
                    if len(chunk) > room:
                        self.truncated = True
        except (OSError, ValueError, AttributeError) as error:
            self.error = type(error).__name__
        finally:
            self._done.set()

    def data(self):
        with self._lock:
            return bytes(self.buffer)

    def wait_for_prefix(self, prefix, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                text = bytes(self.buffer)
            for line in text.splitlines():
                if line.startswith(prefix):
                    return line
            if self._done.is_set():
                return None
            time.sleep(0.02)
        return None

    def finish(self, timeout=10.0):
        self._done.wait(timeout)
        try:
            self._thread.join(timeout)
        except RuntimeError:
            pass
        return self.data()

    def drain_complete(self):
        return bool(self.completed and self._done.is_set() and self.error is None)
