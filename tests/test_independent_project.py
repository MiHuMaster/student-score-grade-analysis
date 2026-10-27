import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.runtime_paths import data_directory
from app import create_app

class IndependentProjectTests(unittest.TestCase):
    def test_unrelated_databases_are_never_selected_or_modified(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, LOCALAPPDATA=tmp), patch.object(sys, 'frozen', True, create=True):
            other = Path(tmp) / 'UnrelatedApplication'
            other.mkdir()
            db = other / 'student_analysis.db'
            db.write_bytes(b'untouched')
            self.assertEqual(data_directory(), Path(tmp) / 'StudentScoreAnalysis')
            self.assertEqual(db.read_bytes(), b'untouched')



    def test_offline_empty_start_and_removed_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp, patch('app.data_directory', return_value=Path(tmp)), patch('socket.create_connection', side_effect=AssertionError('Unexpected outbound connection')):
            app = create_app()
            client = app.test_client()
            self.assertEqual(client.get('/api/exams').status_code, 200)
            self.assertEqual(client.get('/api/exams').json, {'items':[]})
            for path in ('/api/auth/session', '/api/export', '/api/export/summary', '/api/export/score-bands', '/api/export/student/demo'):
                self.assertEqual(client.get(path).status_code, 404, path)
            self.assertEqual(client.post('/api/auth/login', json={}).status_code, 404)
            self.assertNotIn('auth_gateway', app.extensions)
            self.assertFalse((Path(tmp) / 'auth_sessions').exists())
            self.assertFalse((Path(tmp) / 'client_config.json').exists())
            self.assertEqual(client.get('/api/export/classes').status_code, 400)

    def test_local_api_rejects_remote_and_cross_origin_access(self):
        with tempfile.TemporaryDirectory() as tmp, patch('app.data_directory', return_value=Path(tmp)):
            client = create_app().test_client()
            for path, method in [('/api/exams','get'), ('/api/demo-data','delete'), ('/api/import/base','post')]:
                send = getattr(client, method)
                for kwargs in [dict(environ_overrides={'REMOTE_ADDR':'192.0.2.1'}), dict(base_url='http://evil.invalid'), dict(headers={'Origin':'https://evil.invalid'}), dict(headers={'Sec-Fetch-Site':'cross-site'})]:
                    self.assertEqual(send(path, **kwargs).status_code, 403)
            self.assertEqual(client.get('/api/exams', headers={'Origin':'http://localhost','Sec-Fetch-Site':'same-origin'}).status_code, 200)
