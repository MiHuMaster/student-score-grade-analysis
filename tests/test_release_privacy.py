import io
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from release.sanitize_templates import stage_templates, STAGING, compare, sanitize
from release.manifest import ROOT
from release.audit import check_development_paths, audit_sources, check_name


class PrivacyTests(unittest.TestCase):
    def test_templates_and_structure(self):
        report = stage_templates()
        self.assertEqual(len(report), 2)
        for name in report:
            compare(ROOT / name, STAGING / name)
            with zipfile.ZipFile(STAGING / name) as archive:
                for member in archive.namelist():
                    data = archive.read(member)
                    check_development_paths(data, member)
                    if member.startswith('docProps/'):
                        for token in (b'WPS_177', b'Dapanglier', b'KSOTemplateDocerSaveRecord', b'name="ICV"', b'lastModifiedBy', b'dc:creator'):
                            self.assertNotIn(token, data)
            with tempfile.TemporaryDirectory() as temp:
                target = Path(temp) / Path(name).name
                sanitize(STAGING / name, target)
                self.assertEqual(target.read_bytes(), (STAGING / name).read_bytes())

    def test_paths_and_source_audit(self):
        audit_sources()
        with self.assertRaises(ValueError):
            check_name('~$template.xlsx')
        for value in (str(ROOT), 'C:\\Users\\developer\\project', str(ROOT).replace('\\', '/')):
            for encoding in ('utf-8', 'utf-16le'):
                with self.assertRaises(ValueError):
                    check_development_paths(value.encode(encoding), 'fixture')
        # An upstream CI exception must never suppress our own build directory.
        with self.assertRaises(ValueError):
            check_development_paths(str(ROOT).encode(), '_rust.pyd')

    def test_business_mutation_is_rejected(self):
        report = stage_templates()
        with tempfile.TemporaryDirectory() as temp:
            for name in report:
                target = Path(temp) / Path(name).name
                with zipfile.ZipFile(STAGING / name) as source, zipfile.ZipFile(target, 'w') as output:
                    for member in source.infolist():
                        data = source.read(member)
                        if member.filename in {'word/document.xml', 'xl/worksheets/sheet1.xml'}:
                            data += b' '
                        output.writestr(member, data)
                with self.assertRaises(ValueError):
                    compare(ROOT / name, target)

    def test_actual_exports_without_template_file(self):
        from test_system import SystemTestCase
        from app.db import get_db
        from app.services.demo import seed_demo_data
        from app.services import standard_exports as exports
        stage_templates()
        case = SystemTestCase()
        case.setUp()
        try:
            connection = get_db()
            seed_demo_data(connection)
            exam = connection.execute('SELECT exam_key FROM exams ORDER BY exam_date DESC LIMIT 1').fetchone()['exam_key']
            paths = [function(connection, exam, case.app.config['EXPORT_FOLDER']) for function in (
                exports.export_class_zip,)]
            def inspect(data):
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    self.assertIsNone(archive.testzip())
                    for member in archive.namelist():
                        payload = archive.read(member)
                        if member.endswith(('.xlsx', '.docx')):
                            inspect(payload)
                        elif member.endswith('.xml'):
                            from lxml import etree
                            node = etree.fromstring(payload)
                            for value in node.itertext():
                                self.assertIsNone(re.search(r'学生1(?!\d)|学校1(?!\d)|考试名称1(?!\d)', value), member)
            for path in paths:
                inspect(path.read_bytes())
        finally:
            case.tearDown()

    def test_upload_template_sheet_metadata_matches_actual_sheets(self):
        from lxml import etree
        for path in (ROOT / 'templates/upload').glob('*.xlsx'):
            with zipfile.ZipFile(path) as archive:
                workbook = etree.fromstring(archive.read('xl/workbook.xml'))
                names = [node.get('name') for node in workbook.iter() if node.tag.endswith('}sheet')]
                props = etree.fromstring(archive.read('docProps/app.xml'))
                parts = next((node for node in props.iter() if node.tag.endswith('}TitlesOfParts')), None)
                if parts is not None:
                    vector = parts[0]
                    self.assertEqual([node.text for node in vector], names, path.name)
                    self.assertEqual(int(vector.get('size')), len(names))
