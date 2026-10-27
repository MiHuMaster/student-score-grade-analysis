"""The only project resource allowlist used by the spec and release audit."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = (
    "LICENSE",
    "licenses/Inno-Setup-Chinese-Simplified-Translation/LICENSE",
    "licenses/Flask/1-LICENSE.txt",
    "licenses/Werkzeug/1-LICENSE.txt",
    "licenses/Jinja2/1-LICENSE.txt",
    "licenses/MarkupSafe/1-LICENSE.txt",
    "licenses/itsdangerous/1-LICENSE.txt",
    "licenses/click/1-LICENSE.txt",
    "licenses/blinker/1-LICENSE.txt",
    "licenses/openpyxl/1-LICENCE.rst",
    "licenses/et_xmlfile/1-LICENCE.python",
    "licenses/et_xmlfile/2-LICENCE.rst",
    "licenses/Pillow/1-LICENSE",
    "licenses/lxml/1-LICENSE.txt",
    "licenses/lxml/2-LICENSES.txt",
    "licenses/PyInstaller/1-COPYING.txt",
    "licenses/Python-LICENSE.txt",
    "THIRD_PARTY_NOTICES.md",
    "README.md",
    "docs/使用指南.md",
    "docs/核心业务规则.md",
    "docs/字段追踪矩阵.md",

    "app/static/index.html", "app/static/app.js", "app/static/styles.css",
    "app/static/branding/app-icon.png",
    "migrations/001_initial.sql", "migrations/002_composite_student_identity.sql",
    "migrations/003_base_information.sql", "migrations/004_base_class_track.sql",
    "migrations/005_priority1_identity_index.sql", "migrations/006_dynamic_class_targets.sql",
    "templates/upload/基础信息上传标准模板.xlsx",
    "templates/upload/学生赋分成绩填写模板.xlsx",
)
FORBIDDEN_PARTS = {"instance", "uploads", "exports", "backups", "tests", "auth",
                   "auth_sessions", "logs", ".git", ".conda", ".vscode"}
FORBIDDEN_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".bin", ".log", ".env"}


def resource_path(name):
    if Path(name).suffix in {".xlsx", ".docx"}:
        return ROOT / "build/release-templates" / name
    return ROOT / name


def datas():
    try:
        from .sanitize_templates import stage_templates
    except ImportError:
        from sanitize_templates import stage_templates
    stage_templates()
    return [(str(resource_path(name)), str(Path(name).parent)) for name in RESOURCES]
