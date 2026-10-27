"""Isolated Inno runtime checks using the production payload and guard settings.

Only test identity, destination, privileges and shell integration differ. No
installed user copy, registry registration, shortcuts or real data are changed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import unittest

from test_desktop_exit import ROOT, mutex_exists, DesktopExitProcessTests

CHECK = ROOT / '.exit-review' / 'installer-check'
TARGET = CHECK / 'installed'
SETUP = CHECK / 'guard-test.exe'


def prepare():
    CHECK.mkdir(parents=True, exist_ok=True)
    source = (ROOT/'installer/StudentScoreAnalysis.iss').read_text(encoding='utf-8-sig')
    source = source.replace('AppId={{8E8B26B5-AC06-44A1-91BC-DBB748A02F9D}',
                            'AppId=GradeAnalysisExitGuardIsolatedAcceptance')
    source = source.replace('[Setup]', '[Setup]\nSourceDir=' + str(ROOT/'installer') + '\nCreateUninstallRegKey=no')
    source = source.replace('PrivilegesRequired=admin', 'PrivilegesRequired=lowest')
    source = source.replace('DefaultDirName={localappdata}\\Programs\\student-score-analysis', 'DefaultDirName=' + str(TARGET))
    source = source.replace('OutputDir=..\\dist\\installer', 'OutputDir=' + str(CHECK))
    source = source.replace('OutputBaseFilename=student-score-analysis_Setup_{#AppVersion}', 'OutputBaseFilename=guard-test')
    source = source.replace('#include "release-files.iss"', '#include "' + str(ROOT/'installer/release-files.iss') + '"')
    source = source.replace('MessagesFile: "ChineseSimplified.isl"', 'MessagesFile: "' + str(ROOT/'installer/ChineseSimplified.isl') + '"')
    source = source[:source.index('[Icons]')]
    assert 'AppId=GradeAnalysisExitGuardIsolatedAcceptance' in source
    assert 'DefaultDirName=' + str(TARGET) in source
    assert 'CreateUninstallRegKey=no' in source
    assert TARGET.resolve().is_relative_to(ROOT.resolve())
    script = CHECK/'guard-test.iss'
    script.write_text(source, encoding='utf-8-sig')
    with (CHECK/'compile.log').open('w', encoding='utf-8') as log:
        subprocess.run(['C:/Program Files (x86)/Inno Setup 6/ISCC.exe', str(script)], stdout=log, stderr=log, check=True)
    print('Isolated installer compiled with unchanged AppMutex, messages, files and data rules')


def run(mode):
    CHECK.mkdir(parents=True, exist_ok=True)
    blocked = mode.endswith('blocked')
    uninstall = mode.startswith('uninstall')
    assert mutex_exists() == blocked, 'Unexpected running state; do not act'
    executable = TARGET/'unins000.exe' if uninstall else SETUP
    log = CHECK/(mode+'.log')
    before = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in TARGET.rglob('*') if p.is_file()}
    result = subprocess.run([str(executable), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/SP-', '/NORESTART', '/LOG='+str(log)], timeout=90)
    message = log.read_text(encoding='utf-8-sig')
    if blocked:
        assert result.returncode != 0
        assert '完全退出程序' in message and '仍在运行' in message, message
        assert mutex_exists(), 'Installer terminated the desktop'
        after = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in TARGET.rglob('*') if p.is_file()}
        assert after == before, 'Blocked operation changed installed files'
    else:
        assert result.returncode == 0, message
        assert (TARGET/'StudentScoreAnalysis.exe').exists() != uninstall
    print(json.dumps({'mode':mode,'exit_code':result.returncode,'passed':True},ensure_ascii=False))


def lifecycle():
    class InstalledLifecycle(DesktopExitProcessTests):
        executable = TARGET/'StudentScoreAnalysis.exe'

        def on_running(self, attempt):
            run('install-blocked')
            run('uninstall-blocked')

        def on_stopped(self, attempt):
            run('install' if attempt == 0 else 'uninstall')

    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(InstalledLifecycle))
    if not result.wasSuccessful() or result.skipped:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['prepare','install-blocked','install','uninstall-blocked','uninstall','lifecycle'])
    args = parser.parse_args()
    if args.mode == 'prepare':
        prepare()
    elif args.mode == 'lifecycle':
        lifecycle()
    else:
        run(args.mode)
