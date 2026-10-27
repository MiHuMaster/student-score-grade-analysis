param([switch]$OnedirOnly, [string]$PythonExe)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $projectRoot
$buildTemp = Join-Path $projectRoot '.test-work\tmp'
New-Item -ItemType Directory -Force -Path $buildTemp | Out-Null
$env:TEMP = $buildTemp
$env:TMP = $buildTemp
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYINSTALLER_CONFIG_DIR = Join-Path $projectRoot 'build\pyinstaller-cache'
$python = if ($PythonExe) { $PythonExe } else { Join-Path $projectRoot '.release-venv\Scripts\python.exe' }
function Invoke-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Program (exit $LASTEXITCODE)" }
}
if (!(Test-Path -LiteralPath $python)) {
    throw 'Create .release-venv with Python 3.10 x64 and install release/requirements-lock.txt first. See release/README.md.'
}
Invoke-Checked $python @('-c', "import sys,struct; assert sys.version_info[:2] == (3,10) and struct.calcsize('P') == 8")
Invoke-Checked $python @('release/audit.py')
Invoke-Checked $python @('-m', 'unittest', 'discover', '-s', 'tests')
Invoke-Checked 'node' @('--check', 'app/static/app.js')
Invoke-Checked $python @('release/make_icon.py')
Invoke-Checked $python @('-m', 'PyInstaller', '--noconfirm', '--clean', 'StudentScoreAnalysis.spec')
Invoke-Checked $python @('release/audit.py', '--output', 'dist/StudentScoreAnalysis', '--installer-files')
if ($OnedirOnly) { Write-Host 'Onedir built and audited. Installer intentionally not compiled.'; exit 0 }
$compiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
$iscc = if ($compiler) { $compiler.Source } else { $null }
foreach ($candidate in @('C:\Program Files (x86)\Inno Setup 6\ISCC.exe', 'C:\Program Files\Inno Setup 6\ISCC.exe')) {
    if (!$iscc -and (Test-Path -LiteralPath $candidate)) { $iscc = $candidate }
}
if (!$iscc) { throw 'Onedir passed. Install official Inno Setup 6 (https://jrsoftware.org/isdl.php), then rerun release/build.ps1.' }
Invoke-Checked $python @('release/smoke.py')
Invoke-Checked $iscc @('installer/StudentScoreAnalysis.iss')
Write-Host 'Setup created: dist\installer\student-score-analysis_Setup_1.0.0.exe'
