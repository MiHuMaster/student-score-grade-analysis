"""首发前显示及目标方案回归；全部使用隔离的合成数据。"""
import tempfile
import unittest
from xml.etree import ElementTree as ET
from pathlib import Path
from io import BytesIO
from zipfile import ZipFile
from unittest.mock import patch

from app import create_app
from app.db import get_db
from app.services.demo import seed_demo_data
from app.services.analytics import Scope, overview, class_metrics, filter_options, score_bands


class RC2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({'TESTING': True, 'DATABASE': str(Path(self.tmp.name) / 'test.db'), 'UPLOAD_FOLDER': self.tmp.name, 'EXPORT_FOLDER': self.tmp.name})
        self.context = self.app.app_context()
        self.context.push()
        self.db = get_db()
        seed_demo_data(self.db)
        self.exam = self.db.execute('SELECT * FROM exams ORDER BY exam_date DESC LIMIT 1').fetchone()
        self.key = self.exam['exam_key']
        self.scope = Scope(self.key, '物理')
        self.db.execute('DELETE FROM class_stage_targets')
        for row in self.db.execute('SELECT id FROM classes').fetchall():
            for order, (name, count) in enumerate([('一诊', 2), ('二诊', 4), ('高考', 6)]):
                self.db.execute("INSERT INTO class_stage_targets(class_id,target_name,target_order,target_count,source) VALUES (?,?,?,?, 'test')", (row['id'], name, order, count))
        self.db.commit()

    def tearDown(self):
        self.context.pop()
        self.tmp.cleanup()

    def test_target_options_default_explicit_missing_and_non_target_invariance(self):
        options = filter_options(self.db, self.key)
        self.assertEqual(options['targets'], ['一诊', '二诊', '高考'])
        self.assertEqual(options['default_target_name'], '高考')
        client = self.app.test_client()
        response = client.get('/api/filters', query_string={'exam_key': self.key})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['targets'], options['targets'])
        default = class_metrics(self.db, self.scope)
        selected = class_metrics(self.db, self.scope, target_name='一诊目标')
        self.assertEqual(default['target_name'], '高考')
        self.assertTrue(all(item['target'] == 6 for item in default['classes']))
        self.assertTrue(all(item['target'] == 2 for item in selected['classes']))
        for snapshot in selected['history']:
            self.assertTrue(all(item['target'] == 2 for item in snapshot['classes']))
        target_fields = {'target', 'target_name', 'target_completion_rate'}
        for before, after in zip(default['classes'], selected['classes']):
            self.assertEqual({k: v for k,v in before.items() if k not in target_fields}, {k: v for k,v in after.items() if k not in target_fields})
        first = overview(self.db, self.scope)
        second = overview(self.db, self.scope, target_name='一诊')
        self.assertEqual({k:v for k,v in first.items() if k not in {'scope', 'targets'}}, {k:v for k,v in second.items() if k not in {'scope', 'targets'}})
        self.assertTrue(all(item['target'] == 2 for item in second['targets']['details']))
        for endpoint in ('overview', 'classes'):
            response = client.get('/api/analytics/' + endpoint, query_string={'exam_key': self.key, 'track': '物理', 'target_name': '不存在'})
            self.assertEqual(response.status_code, 400)
        class_id = selected['classes'][0]['class_id']
        self.db.execute("DELETE FROM class_stage_targets WHERE class_id=? AND target_name='一诊'", (class_id,))
        missing = class_metrics(self.db, self.scope, target_name='一诊')
        item = next(item for item in missing['classes'] if item['class_id'] == class_id)
        self.assertIsNone(item['target'])
        self.assertIsNone(item['target_completion_rate'])
        self.db.execute("DELETE FROM class_stage_targets WHERE target_name='高考'")
        self.assertIsNone(filter_options(self.db, self.key)['default_target_name'])
        missing = class_metrics(self.db, self.scope)
        self.assertIn('未设置默认高考目标', missing['target_missing_reason'])
        self.assertTrue(all(item['target'] is None for item in missing['classes']))
        self.assertEqual(overview(self.db, self.scope)['targets']['configured_classes'], 0)



    def test_line_band_business_headers_preserve_each_exam_ranges(self):
        expected = ['0-线下90分', '线下90分-线下40分', '线下40分-特控线', '特控线-211线', '211线-985线', '985线以上']
        data = score_bands(self.db, self.scope)
        self.assertEqual([item['display_label'] for item in data['line_bands']], expected)
        for item in data['history']:
            self.assertEqual([band['display_label'] for band in item['line_bands']], expected)
            self.assertEqual(sum(band['count'] for band in item['line_bands']), item['reference_count'])
