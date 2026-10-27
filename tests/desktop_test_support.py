"""Isolate real launcher tests from installed desktops without changing production defaults."""
import hashlib
import json
import os
import socket
from pathlib import Path


def test_mutex(directory):
    suffix = hashlib.sha256(str(Path(directory).resolve()).encode()).hexdigest()[:24]
    return "Local\\GradeManagerTest." + suffix


def available_ports(count=3):
    listeners = []
    try:
        for _ in range(count):
            listener = socket.socket()
            listeners.append(listener)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(('127.0.0.1', 0))
        return sorted(listener.getsockname()[1] for listener in listeners)
    finally:
        for listener in listeners:
            listener.close()


def configure_worker():
    import app.desktop_instance as desktop
    desktop.APP_MUTEX = test_mutex(os.environ['LOCALAPPDATA'])
    desktop.PORTS = tuple(json.loads(os.environ['GRADE_TEST_PORTS']))
    original_bind = desktop.bind_listener
    desktop.bind_listener = lambda: original_bind(desktop.PORTS)
