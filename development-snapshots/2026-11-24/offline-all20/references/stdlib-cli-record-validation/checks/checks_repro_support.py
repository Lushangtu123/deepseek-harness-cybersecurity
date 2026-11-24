#!/usr/bin/env python3
"""Small effect-free process doubles shared by the revision-6 checks."""
import os


class FakeProcess:
    pid = os.getpid()
    stdin = None
    stdout = None
    stderr = None


def fake_popen():
    return FakeProcess()


def fake_identity():
    return {
        "pid": os.getpid(),
        "pgid": os.getpgid(0),
        "starttime": 1,
        "bootId": "synthetic-boot",
        "groupLeader": True,
    }
