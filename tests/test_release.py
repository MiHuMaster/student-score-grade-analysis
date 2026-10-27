from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.runtime_paths import data_directory
from release.audit import audit_sources, check_bytes, check_name
from release.manifest import RESOURCES, ROOT


class ReleaseTests(unittest.TestCase):
    def test_manifest_only_explicit_safe_files(self):
        audit_sources()
        for name in RESOURCES:
            self.assertNotIn('*', name)
            self.assertTrue((ROOT / name).is_file())

    def test_reject_database_and_historical_content(self):
        for name in ('student_analysis.db', 'renamed.sqlite', 'uploads/a.xlsx',
                     'exports/report.xlsx', 'backups/data', 'auth/credential.bin', '.env'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                check_name(name)
        with self.assertRaises(ValueError):
            check_bytes(b'SQLite format 3\x00' + b'0' * 100, 'renamed.dat')

    def test_reject_secret_values(self):
        for data in (b'sb_secret_' + b'x' * 30,
                     b'eyJ' + b'a' * 20 + b'.' + b'b' * 20 + b'.' + b'c' * 20,
                     b'{"refresh_token": "' + b'x' * 20 + b'"}',
                     b'postgresql://admin:private-password@host/db'):
            with self.assertRaises(ValueError):
                check_bytes(data, 'fixture')

    def test_source_directory_unchanged(self):
        self.assertEqual(data_directory(), ROOT / 'instance')

    def test_frozen_new_user_and_writable_path(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, LOCALAPPDATA=temp), patch.object(sys, 'frozen', True, create=True):
            folder = data_directory()
            self.assertEqual(folder, Path(temp) / 'StudentScoreAnalysis')
            folder.mkdir()
            (folder / 'probe').write_bytes(b'ok')



    def test_frozen_missing_localappdata_fails(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(sys, 'frozen', True, create=True):
            with self.assertRaises(RuntimeError):
                data_directory()

    def test_new_empty_database_migrations_and_existing_database(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, LOCALAPPDATA=temp), patch.object(sys, 'frozen', True, create=True):
            app = create_app({'TESTING': True})
            database = Path(app.config['DATABASE'])
            self.assertEqual(database.parent, data_directory())
            with closing(sqlite3.connect(database)) as db:
                for table in ('organizations', 'grades', 'classes', 'students', 'exams',
                              'exam_results', 'subject_scores', 'import_batches',
                              'base_students', 'base_school_classes'):
                    self.assertEqual(db.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT count(*) FROM schema_migrations').fetchone()[0], 6)
                db.execute('CREATE TABLE release_preserve_test (value TEXT)')
                db.execute("INSERT INTO release_preserve_test VALUES ('keep')")
                db.commit()
            create_app({'TESTING': True})
            with closing(sqlite3.connect(database)) as db:
                self.assertEqual(db.execute('SELECT value FROM release_preserve_test').fetchone()[0], 'keep')
            for key in ('UPLOAD_FOLDER', 'EXPORT_FOLDER'):
                self.assertTrue(Path(app.config[key]).is_relative_to(database.parent))

    def test_frozen_static_and_export_resources(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, LOCALAPPDATA=temp), patch.object(sys, 'frozen', True, create=True):
            app = create_app({'TESTING': True})
            client = app.test_client()
            for url in ('/', '/static/app.js', '/static/branding/app-icon.png', '/static/branding/app-icon.png'):
                response = client.get(url)
                self.assertEqual(response.status_code, 200)
                response.close()
            from app.services.standard_exports import _new_class_workbook
            book = _new_class_workbook()
            self.assertIn("物理", book.sheetnames)
            book.close()

    def test_icon_sizes(self):
        from PIL import Image
        with Image.open(ROOT / 'release/app.ico') as icon:
            self.assertEqual(icon.ico.sizes(), {(n, n) for n in (16, 24, 32, 48, 64, 128, 256)})

    def test_installer_preserves_userdata(self):
        source = (ROOT / 'installer/StudentScoreAnalysis.iss').read_text(encoding='utf-8')
        self.assertNotIn('[UninstallDelete]', source)
        self.assertIn('DefaultDirName={localappdata}\\Programs\\student-score-analysis'.replace('\\\\', '\\'), source)
        self.assertIn('PrivilegesRequired=lowest', source)
        self.assertIn('runasoriginaluser', source)
        self.assertIn('Tasks: desktopicon', source)
        self.assertNotIn('Flags: unchecked', source)

    def test_installer_mutex_and_chinese_exit_instructions(self):
        from app.desktop_instance import APP_MUTEX
        source = (ROOT / 'installer/StudentScoreAnalysis.iss').read_text(encoding='utf-8')
        self.assertIn('AppMutex=' + APP_MUTEX, source)
        self.assertIn('CloseApplications=no', source)
        self.assertNotIn('CloseApplications=force', source)
        self.assertIn('MessagesFile: "ChineseSimplified.isl"', source)
        for message in ('SetupAppRunningError', 'UninstallAppRunningError'):
            line = next(line for line in source.splitlines() if line.startswith(message + '='))
            for text in ('仍在运行', '完全退出程序', '确定', '取消'):
                self.assertIn(text, line)


if __name__ == '__main__':
    unittest.main()
