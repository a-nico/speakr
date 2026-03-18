$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $projectRoot

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    throw 'PyInstaller is not installed or not on PATH. Run: pip install -r requirements.txt'
}

Write-Host 'Building Speakr with PyInstaller...'
& pyinstaller --noconfirm .\speakr.spec

if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host 'Build complete. Output is in .\dist\speakr.exe'