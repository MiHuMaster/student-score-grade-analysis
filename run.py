"""Loopback-only Windows desktop launcher (no console or debugger)."""
import logging
import os
import sys
import threading
import webbrowser
from logging.handlers import RotatingFileHandler

from app import create_app
from app.runtime_paths import data_directory
from app.desktop_instance import DesktopInstance, bind_listener, HOST, mark_desktop_running, register_desktop_exit
from pathlib import Path
from werkzeug.serving import make_server, WSGIRequestHandler


def main():
    directory = data_directory()
    directory.mkdir(parents=True, exist_ok=True)
    # Shared by source/frozen launchers for this Windows user, independent of browser state.
    local = os.environ.get("LOCALAPPDATA")
    instance = DesktopInstance(Path(local) / "StudentScoreAnalysis" / "desktop" if local else directory / "desktop")
    try:
        existing_url = instance.acquire()
        if existing_url:
            webbrowser.open(existing_url)
            return
        run_server(directory, instance)
    finally:
        instance.close()


def run_server(directory, instance):
    log_directory = directory / "logs"
    log_directory.mkdir(exist_ok=True)
    logger = logging.getLogger("desktop")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(log_directory / "app.log", maxBytes=1_000_000,
                                  backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    try:
        app = create_app()
        app.debug = False

        class QuietHandler(WSGIRequestHandler):
            # Browser preconnect sockets may never send a request. Bound idle
            # network waits so joining request threads cannot hang shutdown.
            # This does not impose a deadline on application/DB execution.
            timeout = 10

            def log(self, type, message, *args):
                # URLs and request values must not enter desktop logs.
                pass

        with bind_listener() as listener:
            port = listener.getsockname()[1]
            server = make_server(HOST, port, instance.middleware(app), threaded=True,
                                 request_handler=QuietHandler, fd=listener.fileno())
        url = f"http://{HOST}:{port}/"
        try:
            # Wait for active imports/exports and DB teardown before process exit.
            server.daemon_threads = False
            server.block_on_close = True
            register_desktop_exit(app, server, port)
            mark_desktop_running()
            instance.publish(port)
            threading.Timer(0.5, webbrowser.open, args=(url,)).start()
            logger.info("Desktop server started on %s:%s", HOST, port)
            server.serve_forever()
        finally:
            server.server_close()
    except BaseException as error:
        logger.error("Startup/server failure: %s", type(error).__name__)
        raise

    finally:
        handler.close()
        logger.removeHandler(handler)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        if os.name == "nt" and getattr(sys, "frozen", False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                "启动失败。请检查本地 5050–5100 端口是否全部不可用、用户数据目录是否可写，"
                "请保留原数据并检查日志。",
                "student-score-analysis", 0x10,
            )
        raise
else:
    # Preserve the existing `flask --app run` / WSGI import entry point.
    app = create_app()
