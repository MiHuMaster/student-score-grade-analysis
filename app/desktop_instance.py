"""Loopback listener allocation and per-Windows-user desktop instance handshake."""
from __future__ import annotations

import errno
import http.client
import json
import os
import secrets
import socket
import time
import threading
from pathlib import Path

HOST = "127.0.0.1"
PORTS = range(5050, 5101)
APP_MUTEX = r"Global\StudentScoreAnalysis.Running"
# Keep this handle until Windows tears down the process, including request draining.
_installer_mutex = None


def mark_desktop_running():
    global _installer_mutex
    if os.name != "nt" or _installer_mutex is not None:
        return
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel.CreateMutexW(None, False, APP_MUTEX)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    _installer_mutex = handle


def register_desktop_exit(app, server, port):
    """Desktop-only shutdown: loopback, same origin and a per-process random token."""
    from flask import jsonify, request

    token = secrets.token_hex(32)
    origin = f"http://{HOST}:{port}"
    stopping = threading.Event()
    guard = threading.Lock()

    def authorize():
        if (request.remote_addr not in {"127.0.0.1", "::1"}
                or request.host_url.rstrip("/") != origin
                or request.headers.get("Origin", origin) != origin
                or request.headers.get("Sec-Fetch-Site") not in (None, "same-origin", "none")):
            return jsonify(error="仅允许本机页面操作"), 403
        return None

    def exit_token():
        denied = authorize()
        if denied is not None:
            return denied
        response = jsonify(token=token)
        response.headers["Cache-Control"] = "no-store"
        return response

    def shutdown():
        denied = authorize()
        if denied is not None:
            return denied
        if not secrets.compare_digest(request.headers.get("X-GradeAnalysis-Exit-Token", "").encode("utf-8"), token.encode("ascii")):
            return jsonify(error="退出验证失败，请重试"), 403
        with guard:
            if not stopping.is_set():
                stopping.set()
                # shutdown must run outside the serve_forever thread. Give the
                # response time to reach the page; server_close joins all requests.
                threading.Timer(0.5, server.shutdown).start()
        response = jsonify(stopping=True)
        response.headers["Cache-Control"] = "no-store"
        return response

    app.add_url_rule("/api/desktop/exit-token", "desktop_exit_token", exit_token, methods=["GET"])
    app.add_url_rule("/api/desktop/shutdown", "desktop_shutdown", shutdown, methods=["POST"])


def bind_listener(ports=PORTS):
    # Keep the selected socket bound: there is no probe/close/rebind race.
    for port in ports:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name == "nt":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind((HOST, port))
            listener.listen(socket.SOMAXCONN)
            return listener
        except OSError as error:
            listener.close()
            if error.errno not in (errno.EADDRINUSE, errno.EACCES) and getattr(error, "winerror", None) not in (10048, 10013):
                raise
    raise RuntimeError("No available loopback port in 5050-5100")


class DesktopInstance:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.state_path = directory / "instance.json"
        self.lock = (directory / "instance.lock").open("a+b")
        if self.lock.tell() == 0:
            self.lock.write(b"0")
            self.lock.flush()
        self.owned = False
        self.nonce = secrets.token_hex(32)

    def acquire(self, timeout=20):
        import msvcrt
        deadline = time.monotonic() + timeout
        while True:
            self.lock.seek(0)
            try:
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
            else:
                self.owned = True
                self.state_path.unlink(missing_ok=True)
                return None
            url = self.peer_url()
            if url:
                return url
            if time.monotonic() >= deadline:
                raise RuntimeError("Existing desktop instance did not become ready")
            time.sleep(0.1)

    def peer_url(self):
        connection = None
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            port, nonce = state["port"], state["nonce"]
            if type(port) is not int or port not in PORTS or not isinstance(nonce, str) or len(nonce) != 64:
                return None
            connection = http.client.HTTPConnection(HOST, port, timeout=0.4)
            connection.request("GET", "/_ssa_instance/" + nonce)
            response = connection.getresponse()
            if response.status == 200 and response.read(256) == nonce.encode("ascii"):
                return f"http://{HOST}:{port}/"
        except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
            pass
        finally:
            if connection:
                connection.close()
        return None

    def publish(self, port):
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"port": port, "pid": os.getpid(), "nonce": self.nonce}), encoding="utf-8")
        os.replace(temporary, self.state_path)

    def middleware(self, application):
        def dispatch(environ, start_response):
            if environ.get("PATH_INFO") == "/_ssa_instance/" + self.nonce:
                body = self.nonce.encode("ascii")
                start_response("200 OK", [("Content-Type", "text/plain"),
                                          ("Content-Length", str(len(body))), ("Cache-Control", "no-store")])
                return [body]
            return application(environ, start_response)
        return dispatch

    def close(self):
        try:
            if self.owned:
                self.state_path.unlink(missing_ok=True)
        finally:
            self.lock.close()
