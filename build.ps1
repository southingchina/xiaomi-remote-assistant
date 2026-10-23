$ErrorActionPreference='Stop'
$projectRoot=$PSScriptRoot
$pythonExe=Join-Path $projectRoot '.venv\Scripts\python.exe'
$evidence=Join-Path $projectRoot 'evidence\0.1.1'
New-Item -ItemType Directory -Path $evidence -Force | Out-Null
$buildLog=Join-Path $evidence 'build.log'
Set-Location -LiteralPath $projectRoot
& $pythonExe -X utf8 -m unittest discover -s tests -p 'test_*.py'
if($LASTEXITCODE -ne 0){throw 'Tests failed'}
& node --test tests/test_capture_v4.mjs tests/test_ui_save.mjs
if($LASTEXITCODE -ne 0){throw 'JavaScript tests failed'}
& $pythonExe -m PyInstaller 'XiaomiRemote.spec' --noconfirm *> $buildLog
if($LASTEXITCODE -ne 0){throw 'PyInstaller failed; inspect evidence/build.log'}
$compiler=Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
& $compiler /nologo /target:winexe '/reference:System.Windows.Forms.dll' '/out:dist\XiaomiRemoteAssistant\XiaomiRemoteAssistant.exe' 'launcher.cs'
if($LASTEXITCODE -ne 0){throw 'Desktop launcher compile failed'}
& $pythonExe 'package_source.py'
if($LASTEXITCODE -ne 0){throw 'Source packaging failed'}
$inno=Join-Path $projectRoot 'tools\InnoSetup\ISCC.exe'
& $inno 'installer.iss' *> (Join-Path $evidence 'installer-build.log')
if($LASTEXITCODE -ne 0){throw 'Installer compilation failed'}
Get-ChildItem -LiteralPath (Join-Path $projectRoot 'release') -File | Where-Object Extension -in '.exe','.zip' | Get-FileHash -Algorithm SHA256 | ForEach-Object { $_.Hash.ToLower()+'  '+[IO.Path]::GetFileName($_.Path) } | Set-Content -LiteralPath (Join-Path $projectRoot 'release\SHA256SUMS.txt') -Encoding utf8
