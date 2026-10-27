"""Real sockets and independent launcher processes; never stop existing applications."""
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import errno
from unittest.mock import MagicMock, patch
from pathlib import Path

from app.desktop_instance import DesktopInstance, HOST, PORTS, bind_listener
from desktop_test_support import available_ports

ROOT = Path(__file__).resolve().parents[1]
WORKER = r'''
import json, os, runpy, sys, webbrowser
from pathlib import Path
from desktop_test_support import configure_worker
configure_worker()
sys.frozen = True
def opened(url):
    with (Path(os.environ['LOCALAPPDATA']) / 'browser.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps({'pid': os.getpid(), 'url': url}) + '\n')
    return True
webbrowser.open = opened
runpy.run_path('run.py', run_name='__main__')
'''


class DesktopPortTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.local = Path(self.temp.name)
        self.processes = []
        self.logs = []
        self.ports = available_ports()
        port_patch = patch('app.desktop_instance.PORTS', self.ports)
        port_patch.start()
        self.addCleanup(port_patch.stop)

    def tearDown(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=10)
        for stream in self.logs:
            stream.close()
        self.temp.cleanup()

    def launch(self):
        env = os.environ.copy()
        env['LOCALAPPDATA'] = str(self.local)
        env['GRADE_TEST_PORTS'] = json.dumps(self.ports)
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        # Windows venv python.exe is a redirector: use the real interpreter so
        # Popen.pid and termination belong to the process running this fixture.
        env['PYTHONPATH'] = os.pathsep.join(path for path in sys.path if path)

        stream = (self.local / f'child-{len(self.processes)}.log').open('w')
        self.logs.append(stream)
        process = subprocess.Popen([sys._base_executable, '-c', WORKER], cwd=ROOT, env=env,
                                   stdout=stream, stderr=stream, creationflags=subprocess.CREATE_NO_WINDOW)
        self.processes.append(process)
        return process

    def ready(self, process):
        deadline = time.monotonic() + 30
        state_path = self.local / 'StudentScoreAnalysis/desktop/instance.json'
        while time.monotonic() < deadline:
            self.assertIsNone(process.poll(), 'Launcher exited unexpectedly')
            try:
                state = json.loads(state_path.read_text())
                connection = http.client.HTTPConnection(HOST, state['port'], timeout=0.3)
                try:
                    connection.request('GET', '/_ssa_instance/' + state['nonce'])
                    response = connection.getresponse()
                    if response.status == 200 and response.read() == state['nonce'].encode():
                        return state
                finally:
                    connection.close()
            except (OSError, ValueError, http.client.HTTPException):
                pass
            time.sleep(0.05)
        details = '\n'.join(path.read_text(errors='replace') for path in self.local.glob('child-*.log'))
        self.fail('Launcher did not become ready: ' + details)

    def browser_calls(self, count):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                calls = [json.loads(line) for line in (self.local / 'browser.jsonl').read_text().splitlines()]
                if len(calls) >= count:
                    return calls
            except (OSError, ValueError):
                pass
            time.sleep(0.05)
        self.fail('Browser was not opened')

    def occupy(self, port):
        listener = socket.socket()
        try:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind((HOST, port))
            listener.listen()
            return listener
        except OSError:
            listener.close()
            raise

    def test_free_first_port_and_browser_matches_real_listener(self):
        # The default 5050 ordering is separately verified without claiming a live port.
        state = self.ready(self.launch())
        self.assertEqual(state['port'], self.ports[0])
        self.assertEqual(self.browser_calls(1)[0]['url'], f'http://{HOST}:{self.ports[0]}/')

    def test_unrelated_listener_fallback_and_repeat_launch(self):
        # This socket belongs to the test parent, not the application child.
        blocker = self.occupy(self.ports[0])
        with blocker:
            first = self.launch()
            state = self.ready(first)
            self.assertGreater(state['port'], blocker.getsockname()[1])
            self.assertIn(state['port'], self.ports)
            expected = f"http://127.0.0.1:{state['port']}/"
            self.assertEqual(self.browser_calls(1)[0]['url'], expected)
            second = self.launch()
            self.assertEqual(second.wait(timeout=15), 0)
            self.assertIsNone(first.poll())
            self.assertEqual(self.ready(first), state)
            self.assertEqual(self.browser_calls(2)[1], {'pid': second.pid, 'url': expected})
            self.assertEqual(blocker.getsockname()[0], HOST)

    def test_available_default_port_selected_without_probing_other_ports(self):
        listener = MagicMock()
        with patch('app.desktop_instance.socket.socket', return_value=listener) as factory:
            self.assertIs(bind_listener(), listener)
        factory.assert_called_once()
        listener.bind.assert_called_once_with((HOST, 5050))
        listener.close.assert_not_called()

    def test_all_51_ports_busy_stops_and_closes_sockets(self):
        listener = MagicMock()
        listener.bind.side_effect = OSError(errno.EADDRINUSE, 'busy')
        with patch('app.desktop_instance.socket.socket', return_value=listener) as factory:
            with self.assertRaises(RuntimeError):
                bind_listener()
        self.assertEqual(factory.call_count, 51)
        self.assertEqual(listener.close.call_count, 51)
        self.assertEqual([call.args[0] for call in listener.bind.call_args_list], [(HOST, p) for p in PORTS])

    def test_simultaneous_launches_share_one_server(self):
        first, second = self.launch(), self.launch()
        deadline = time.monotonic() + 30
        while first.poll() is None and second.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        live = [p for p in (first, second) if p.poll() is None]
        self.assertEqual(len(live), 1)
        self.assertEqual(next(p for p in (first, second) if p not in live).returncode, 0)
        state = self.ready(live[0])
        calls = self.browser_calls(2)
        self.assertTrue(all(c['url'] == f"http://{HOST}:{state['port']}/" for c in calls))

    def test_listener_is_exclusive_and_loopback_only(self):
        with bind_listener(self.ports) as listener:
            self.assertEqual(listener.getsockname()[0], HOST)
            with self.assertRaises(OSError):
                self.occupy(listener.getsockname()[1])

    def test_finite_exhaustion(self):
        with self.occupy(0) as blocker:
            with self.assertRaises(RuntimeError):
                bind_listener([blocker.getsockname()[1]])

    def test_stale_state_not_trusted_after_owner_exit(self):
        path = self.local / 'state'
        old = DesktopInstance(path)
        self.assertIsNone(old.acquire())
        old.publish(5050)
        # Simulate abrupt exit: Windows releases the handle but leaves metadata.
        old.lock.close()
        new = DesktopInstance(path)
        try:
            self.assertIsNone(new.acquire())
            self.assertFalse(new.state_path.exists())
        finally:
            new.close()

    def test_wrong_service_is_not_accepted_as_own_instance(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        class OtherHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'unrelated-service')
            def log_message(self, *args):
                pass
        with bind_listener(self.ports) as listener:
            port = listener.getsockname()[1]
        server = ThreadingHTTPServer((HOST, port), OtherHandler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        owner = DesktopInstance(self.local / 'state')
        peer = DesktopInstance(self.local / 'state')
        try:
            owner.acquire()
            owner.publish(port)
            with self.assertRaises(RuntimeError):
                peer.acquire(timeout=0.2)
        finally:
            peer.close()
            owner.close()
            server.shutdown()
            thread.join()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
