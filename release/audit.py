"""Fail-closed release checks. Never print matched secret values."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import marshal
import os
import re
import zipfile
from pathlib import Path

try:
    from .manifest import ROOT, RESOURCES, FORBIDDEN_PARTS, FORBIDDEN_SUFFIXES, resource_path
except ImportError:
    from manifest import ROOT, RESOURCES, FORBIDDEN_PARTS, FORBIDDEN_SUFFIXES, resource_path

PATTERNS = [
    rb"sb_secret_[A-Za-z0-9_-]+",
    rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s+[A-Za-z0-9+/=]{32,}",
    rb"(?:postgres|postgresql)://[^\s\"']+:[^\s\"']+@",
    rb"(?i)(?:SUPABASE_SERVICE_ROLE_KEY|SUPABASE_SECRET_KEY)\s*[=:]\s*[\"']?[A-Za-z0-9_-]{12,}",
    rb"(?i)[\"'](?:access_token|refresh_token|password)[\"']\s*:\s*[\"'][^\"'\s]{8,}[\"']",
    rb"YJTEST01",
]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_name(path):
    path = Path(path)
    if (set(part.lower() for part in path.parts) & FORBIDDEN_PARTS
            or path.suffix.lower() in FORBIDDEN_SUFFIXES
            or path.name.lower().startswith((".env", "student_analysis.db", "~$"))):
        raise ValueError(f"Forbidden release path: {path}")


def check_bytes(data, label):
    if data.startswith(b"SQLite format 3\x00"):
        raise ValueError(f"SQLite payload: {label}")
    for pattern in PATTERNS:
        for match in re.finditer(pattern, data):
            # Exact pydantic documentation placeholder, not a configured DSN.
            if label == "PYZ:pydantic.networks" and match.group() == b"postgres://user:pass@":
                continue
            if label == "PYZ:pydantic.types" and match.group() == b'"password":"IAmSensitive"':
                continue
            raise ValueError(f"Potential credential in {label} (value withheld)")
    for name in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY",
                 "SUPABASE_DB_PASSWORD", "DATABASE_PASSWORD"):
        value = os.environ.get(name, "")
        if len(value) >= 8 and value.encode() in data:
            raise ValueError(f"Environment secret in {label} (value withheld)")


def check_development_paths(data, label):
    for encoding in ('utf-8', 'utf-16le'):
        decoded = data.decode(encoding, errors='ignore').replace('\\\\', '\\').replace('/', '\\')
        # Upstream Windows wheel CI source locations, not this developer's data.
        # Keep the shipped binaries intact; allow only the inspected runner prefixes.
        if label in {'_rust.pyd', '_pydantic_core.cp310-win_amd64.pyd'}:
            decoded = re.sub(r'(?i)C:\\Users\\runneradmin\\\.cargo\\registry\\src\\', '<upstream-ci>\\\\', decoded)
        if label == '_quoting_c.cp310-win_amd64.pyd':
            decoded = re.sub(r'(?i)C:\\Users\\RUNNER~1\\AppData\\Local\\Temp\\\.tmp-yarl-pep517-[a-z0-9]+\\src\\yarl\\', '<upstream-ci>\\\\', decoded)
        if label == '_helpers_c.cp310-win_amd64.pyd':
            decoded = re.sub(r'(?i)C:\\Users\\RUNNER~1\\AppData\\Local\\Temp\\\.tmp-propcache-pep517-[a-z0-9]+\\src\\src\\propcache\\', '<upstream-ci>\\\\', decoded)
        if str(ROOT).lower() in decoded.lower() or re.search(r'(?i)[a-z]:\\Users\\[^\\<>"\s]+\\', decoded):
            raise ValueError(f'Development path in {label} (value withheld)')


def check_file(path, release_output=False):
    data = path.read_bytes()
    check_bytes(data, path.name)
    if release_output:
        check_development_paths(data, path.name)
    if zipfile.is_zipfile(io.BytesIO(data)):
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for member in archive.namelist():
                if not member.endswith("/"):
                    check_name(member)
                    check_bytes(archive.read(member), f"{path.name}:{member}")
                    if release_output:
                        check_development_paths(archive.read(member), f"{path.name}:{member}")


def audit_sources():
    protected = json.loads((ROOT / "release/protected-files.json").read_text(encoding="utf-8"))
    for name, expected in protected.items():
        if digest(ROOT / name) != expected:
            raise ValueError(f"Reviewed source changed: {name}")
    reviewed = json.loads((ROOT / "release/reviewed-resources.json").read_text(encoding="utf-8"))
    for name in RESOURCES:
        check_name(name)
        path = ROOT / name
        check_file(path)
        if path.suffix in {".xlsx", ".docx"} and digest(path) != reviewed.get(name):
            raise ValueError(f"Export template changed; review required: {name}")
    for path in [ROOT / "run.py", *sorted((ROOT / "app").rglob("*.py"))]:
        check_file(path)
    print(f"Source audit passed: {len(RESOURCES)} explicit resources")


def audit_output(folder, write_installer=False):
    audit_sources()
    folder = Path(folder).resolve()
    if not (folder / "StudentScoreAnalysis.exe").is_file():
        raise ValueError("Missing desktop executable")
    internal = folder / "_internal"
    allowed_office = {Path(name).name for name in RESOURCES if Path(name).suffix in {".xlsx", ".docx"}}
    records = {}
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(folder)
        check_name(relative)
        if path.suffix.lower() in {".xlsx", ".xls", ".csv", ".docx"}:
            if path.name not in allowed_office:
                raise ValueError(f"Unlisted document: {relative}")
        check_file(path, release_output=True)
        records[relative.as_posix()] = digest(path)
    for name in RESOURCES:
        if digest(internal / name) != digest(resource_path(name)):
            raise ValueError(f"Bundled resource mismatch: {name}")
    try:
        from .sanitize_templates import compare
    except ImportError:
        from sanitize_templates import compare
    for name in RESOURCES:
        if Path(name).suffix in {'.xlsx', '.docx'}:
            compare(ROOT / name, internal / name)
    # Inspect compressed Python payload too, rather than scanning only the EXE container.
    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader
    archive = CArchiveReader(str(folder / "StudentScoreAnalysis.exe"))
    for name, entry in archive.toc.items():
        if entry[-1] == "s":
            check_bytes(archive.extract(name), f"EXE:{name}")
            check_development_paths(archive.extract(name), f"EXE:{name}")
        elif entry[-1] == "z":
            pyz = archive.open_embedded_archive(name)
            for module in pyz.toc:
                if module.split('.')[0] in {'supabase', 'postgrest', 'realtime', 'storage3', 'supabase_auth', 'supabase_functions', 'flask_session'} or module in {'app.services.auth', 'app.services.credential_store', 'app.client_config', 'app.services.exporter'}:
                    raise ValueError(f'Removed authentication/export module bundled: {module}')
                code = pyz.extract(module)
                if code is not None:
                    check_bytes(marshal.dumps(code), f"PYZ:{module}")
                    check_development_paths(marshal.dumps(code), f"PYZ:{module}")
    report = ROOT / "release/output-manifest.json"
    report.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    if write_installer:
        lines = ["; Generated after successful output audit. Do not edit."]
        for name in records:
            path = folder / name
            source = os.path.relpath(path, ROOT / "installer").replace("/", "\\")
            parent = str(Path(name).parent).replace("/", "\\")
            destination = "{app}" + ("\\" + parent if parent != "." else "")
            lines.append(f'Source: "{source}"; DestDir: "{destination}"; Flags: ignoreversion')
        (ROOT / "installer/release-files.iss").write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    print(f"Output audit passed: {len(records)} files; no database, user data or detected secrets")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--installer-files", action="store_true")
    args = parser.parse_args()
    if args.output:
        audit_output(args.output, args.installer_files)
    else:
        audit_sources()
