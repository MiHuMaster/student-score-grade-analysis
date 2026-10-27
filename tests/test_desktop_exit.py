"""Exit security and real desktop lifecycle, using isolated local data."""
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

import httpx
from app.desktop_instance import APP_MUTEX, DesktopInstance, register_desktop_exit
from app import create_app
from desktop_test_support import available_ports, test_mutex

ROOT = Path(__file__).resolve().parents[1]
SOURCE_WORKER = r'''
import sys, runpy, webbrowser, app, os, time
from pathlib import Path
from desktop_test_support import configure_worker
configure_worker()
sys.frozen = True
webbrowser.open = lambda *a: True
original = app.create_app
def create():
    application = original()
    @application.get('/_test_slow_request')
    def slow():
        root = Path(os.environ['LOCALAPPDATA'])
        (root/'request-started').write_bytes(b'started')
        time.sleep(2)
        (root/'request-completed').write_bytes(b'completed')
        return 'completed'
    return application
app.create_app = create
runpy.run_path('run.py', run_name='__main__')
'''


def mutex_exists(name=APP_MUTEX):
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
    kernel.OpenMutexW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenMutexW(0x100000, False, name)
    if handle:
        kernel.CloseHandle(handle)
    return bool(handle)


class ExitSecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        with patch('app.data_directory', return_value=Path(self.temp.name)):
            self.app = create_app({'TESTING':True})
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp.cleanup()

    def prepare(self):
        self.server = Mock()
        register_desktop_exit(self.app, self.server, 5050)
        self.app.config['SERVER_NAME'] = '127.0.0.1:5050'
        self.client.environ_base['HTTP_HOST'] = '127.0.0.1:5050'
        self.base = 'http://127.0.0.1:5050'

    def test_local_exit_requires_random_token(self):
        self.prepare()
        response = self.client.get('/api/desktop/exit-token', base_url=self.base)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.post('/api/desktop/shutdown', base_url=self.base).status_code, 403)
        with patch('app.desktop_instance.threading.Timer') as timer:
            response = self.client.post('/api/desktop/shutdown', base_url=self.base,
                headers={'X-GradeAnalysis-Exit-Token': response.json['token']})
            self.assertEqual(response.status_code, 200)
            timer.assert_called_once_with(0.5, self.server.shutdown)
        self.server.shutdown.assert_not_called()

    def test_post_only_same_origin_loopback_and_random_token(self):
        self.prepare()
        token_response = self.client.get('/api/desktop/exit-token', base_url=self.base)
        self.assertEqual(token_response.status_code, 200)
        self.assertEqual(token_response.headers['Cache-Control'], 'no-store')
        token = token_response.json['token']
        self.assertEqual(len(token), 64)
        self.assertEqual(self.client.get('/api/desktop/shutdown', base_url=self.base).status_code, 405)
        for headers, remote, base in [({}, '127.0.0.1', self.base),
                ({'X-GradeAnalysis-Exit-Token': 'wrong'}, '127.0.0.1', self.base),
                ({'X-GradeAnalysis-Exit-Token': token, 'Origin':'https://evil.invalid'}, '127.0.0.1', self.base),
                ({'X-GradeAnalysis-Exit-Token': token, 'Sec-Fetch-Site':'cross-site'}, '127.0.0.1', self.base),
                ({'X-GradeAnalysis-Exit-Token': token}, '192.0.2.1', self.base),
                ({'X-GradeAnalysis-Exit-Token': token}, '127.0.0.1', 'http://evil.invalid:5050')]:
            with self.subTest(headers=headers, remote=remote, base=base):
                self.assertEqual(self.client.post('/api/desktop/shutdown', headers=headers, base_url=base, environ_overrides={'REMOTE_ADDR':remote}).status_code, 403)
        self.server.shutdown.assert_not_called()

    def test_exit_is_idempotent(self):
        self.prepare()
        token = self.client.get('/api/desktop/exit-token', base_url=self.base).json['token']
        with patch('app.desktop_instance.threading.Timer') as timer:
            for _ in range(2):
                response = self.client.post('/api/desktop/shutdown', base_url=self.base, headers={'X-GradeAnalysis-Exit-Token':token})
                self.assertEqual(response.status_code, 200)
            timer.assert_called_once_with(0.5, self.server.shutdown)


class DesktopExitProcessTests(unittest.TestCase):
    executable = None


    def on_running(self, attempt):
        pass

    def on_stopped(self, attempt):
        pass

    def test_exit_restart_preserves_data_ports_and_locks(self):
        if self.executable:
            self.assertFalse(mutex_exists(), 'Another NEW desktop is running; do not stop it')
        with tempfile.TemporaryDirectory() as temporary:
            local = Path(temporary)
            mutex_name = APP_MUTEX if self.executable else test_mutex(local)
            self.assertFalse(mutex_exists(mutex_name))
            env = os.environ.copy()
            env.update(LOCALAPPDATA=str(local), GRADE_TEST_PORTS=json.dumps(available_ports()), PYTHONDONTWRITEBYTECODE='1')
            env['BROWSER'] = f'"{Path(sys.executable).as_posix()}" -c pass %s'
            env['PYTHONPATH'] = os.pathsep.join([str(ROOT), *[p for p in sys.path if p]])
            command = [str(self.executable)] if self.executable else [sys._base_executable, '-c', SOURCE_WORKER]
            process = None
            try:
                for attempt in range(2):
                    process = subprocess.Popen(command, cwd=ROOT, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
                    with httpx.Client(trust_env=False, timeout=5) as client:
                        deadline = time.monotonic()+45
                        while True:
                            self.assertIsNone(process.poll())
                            try:
                                state = json.loads((local/'StudentScoreAnalysis/desktop/instance.json').read_text())
                                url = f"http://127.0.0.1:{state['port']}"
                                if state['pid'] == process.pid and client.get(url+'/api/health').status_code == 200:
                                    break
                            except (OSError, ValueError, httpx.TransportError):
                                pass
                            self.assertLess(time.monotonic(), deadline)
                            time.sleep(.05)
                        self.assertTrue(mutex_exists(mutex_name))
                        idle = socket.create_connection(('127.0.0.1',state['port']), timeout=15)
                        self.assertEqual(client.get(url+'/api/exams').status_code, 200)
                        data = local/'StudentScoreAnalysis'
                        (data/'uploads/exit-fixture.txt').write_bytes(b'synthetic upload')
                        (data/'exports/exit-fixture.txt').write_bytes(b'synthetic export')
                        files = [data/'student_analysis.db', data/'uploads/exit-fixture.txt', data/'exports/exit-fixture.txt']
                        self.assertEqual(len(files), 3)
                        hashes = {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
                        self.on_running(attempt)
                        second = subprocess.Popen(command,cwd=ROOT,env=env,creationflags=subprocess.CREATE_NO_WINDOW)
                        self.assertEqual(second.wait(timeout=30),0)
                        slow_thread = None
                        if not self.executable:
                            (local/'request-started').unlink(missing_ok=True)
                            (local/'request-completed').unlink(missing_ok=True)
                            def slow_request():
                                with httpx.Client(trust_env=False, timeout=10) as slow_client:
                                    slow_client.get(url+'/_test_slow_request')
                            slow_thread = threading.Thread(target=slow_request)
                            slow_thread.start()
                            deadline = time.monotonic()+5
                            while not (local/'request-started').exists():
                                self.assertLess(time.monotonic(),deadline)
                                time.sleep(.02)
                        token = client.get(url+'/api/desktop/exit-token').json()['token']
                        response = client.post(url+'/api/desktop/shutdown',headers={'X-GradeAnalysis-Exit-Token':token})
                        self.assertEqual(response.status_code,200,response.text)
                        self.assertEqual(process.wait(timeout=20),0)
                        self.assertEqual(idle.recv(1), b'')
                        idle.close()
                        if slow_thread:
                            slow_thread.join(timeout=5)
                            self.assertEqual((local/'request-completed').read_bytes(),b'completed')
                        self.assertFalse(mutex_exists(mutex_name))
                        self.assertFalse((local/'StudentScoreAnalysis/desktop/instance.json').exists())
                        with socket.socket() as probe:
                            self.assertNotEqual(probe.connect_ex(('127.0.0.1',state['port'])),0)
                        owner = DesktopInstance(local/'StudentScoreAnalysis/desktop')
                        try:
                            self.assertIsNone(owner.acquire(timeout=.2))
                        finally:
                            owner.close()
                        self.assertEqual({p:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, hashes)
                        self.on_stopped(attempt)
                        self.assertEqual({p:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}, hashes)
            finally:
                if process and process.poll() is None:
                    process.terminate()  # Only a failed, isolated test child.
                    process.wait(timeout=15)


if __name__ == '__main__':
    if '--frozen' in sys.argv:
        sys.argv.remove('--frozen')
        DesktopExitProcessTests.executable = ROOT/'dist/StudentScoreAnalysis/StudentScoreAnalysis.exe'
    unittest.main()
