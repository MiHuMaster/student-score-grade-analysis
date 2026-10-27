"""Deterministic release copies; all non-metadata ZIP members remain byte-identical."""
from pathlib import Path
import hashlib
import json
import re
import zipfile
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
STAGING = ROOT / 'build/release-templates'
ALLOWED = {'docProps/core.xml', 'docProps/custom.xml', 'docProps/app.xml', 'xl/workbook.xml'}
PRIVATE_PROPERTIES = {'ICV', 'KSOProductBuildVer', 'KSOTemplateDocerSaveRecord'}


def clean_member(name, data):
    # Surgical byte edits preserve namespace declarations and every unrelated byte.
    if name == 'docProps/core.xml':
        data = re.sub(rb'<(dc:creator|cp:lastModifiedBy)\b[^>]*>.*?</\1>', b'', data, flags=re.S)
    elif name == 'docProps/custom.xml':
        def property_edit(match):
            node = etree.fromstring(b'<root xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">' + match[0] + b'</root>')[0]
            return b'' if node.get('name') in PRIVATE_PROPERTIES else match[0]
        data = re.sub(rb'<property\b[^>]*>.*?</property>', property_edit, data, flags=re.S)
    elif name == 'docProps/app.xml':
        data = re.sub(rb'<Application>WPS Office_[^<]*</Application>', b'<Application>WPS Office</Application>', data)
    elif name == 'xl/workbook.xml':
        data = re.sub(rb'(<x15ac:absPath\b[^>]*\burl=")[^"]*(")', rb'\1\2', data)
    return data


def compare(source, target):
    records = {}
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(target) as after:
        if before.namelist() != after.namelist() or after.testzip():
            raise ValueError('OOXML member list/CRC mismatch')
        for name in before.namelist():
            old, new = before.read(name), after.read(name)
            if new != clean_member(name, old):
                raise ValueError(f'Unexpected template change: {name}')
            if old != new and name not in ALLOWED:
                raise ValueError(f'Business XML changed: {name}')
            if name.endswith('.xml'):
                etree.fromstring(new)
                if re.search(rb'(?i)(?:(?<![a-z])[a-z]:[\\/]|file:///|\\\\[a-z0-9_.-]+\\)', new):
                    raise ValueError(f'Absolute path remains in template: {name}')
            records[name] = {'before': hashlib.sha256(old).hexdigest(), 'after': hashlib.sha256(new).hexdigest(), 'changed': old != new}
    return records


def sanitize(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as before, zipfile.ZipFile(target, 'w') as after:
        after.comment = before.comment
        for info in before.infolist():
            after.writestr(info, clean_member(info.filename, before.read(info)))
    return compare(source, target)


def stage_templates():
    try:
        from .manifest import RESOURCES
    except ImportError:
        from manifest import RESOURCES
    report = {}
    for name in RESOURCES:
        if Path(name).suffix in {'.xlsx', '.docx'}:
            report[name] = sanitize(ROOT / name, STAGING / name)
    (STAGING / 'structure-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    stage_templates()
