$ErrorActionPreference='Stop'
$projectRoot=$PSScriptRoot
$evidence=Join-Path $projectRoot 'evidence\0.1.1'
New-Item -ItemType Directory -Path $evidence -Force | Out-Null
$installTarget=[IO.Path]::GetFullPath((Join-Path $evidence 'install-smoke'))
if(-not $installTarget.StartsWith([IO.Path]::GetFullPath($evidence)+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw 'Unsafe smoke target'}
$setup=Join-Path $projectRoot 'release\XiaomiRemoteAssistant-0.1.1-test-win-x64-Setup.exe'
$oldData=$env:RC003_DATA_DIR
$env:RC003_DATA_DIR=Join-Path $evidence 'install-smoke-data'
try {
    $installLog=Join-Path $evidence 'installer-smoke.log'
    $proc=Start-Process -FilePath $setup -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/DIR="'+$installTarget+'"'),'/TASKS=""','/NOICONS',('/LOG="'+$installLog+'"')) -WindowStyle Hidden -Wait -PassThru
    if($proc.ExitCode -ne 0){throw ('Install failed: '+$proc.ExitCode)}
    # Isolated user profile fixture: reinstall must never overwrite mappings.
    New-Item -ItemType Directory -Path $env:RC003_DATA_DIR -Force | Out-Null
    & (Join-Path $projectRoot '.venv\Scripts\python.exe') -X utf8 -c 'from rc003_bridge.standalone import ProfileResolver; p=ProfileResolver(); s=p.read_state(); s["profiles"][0]["name"]="覆盖安装保留测试"; s["profiles"][0]["bindings"]["6"]["action"]="Delete"; p.save_state(s)'
    if($LASTEXITCODE -ne 0){throw 'Profile fixture failed'}
    $profilePath=Join-Path $env:RC003_DATA_DIR 'profiles.json'
    $profileHash=(Get-FileHash -LiteralPath $profilePath -Algorithm SHA256).Hash
    $reinstallLog=Join-Path $evidence 'reinstaller-smoke.log'
    $reinstall=Start-Process -FilePath $setup -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/DIR="'+$installTarget+'"'),'/TASKS=""','/NOICONS',('/LOG="'+$reinstallLog+'"')) -WindowStyle Hidden -Wait -PassThru
    if($reinstall.ExitCode -ne 0){throw ('Reinstall failed: '+$reinstall.ExitCode)}
    if((Get-FileHash -LiteralPath $profilePath -Algorithm SHA256).Hash -ne $profileHash){throw 'Reinstall modified user mappings'}
    $core=Join-Path $installTarget 'XiaomiRemoteCore.exe'
    $selfTest=Join-Path $evidence 'installed-self-test.json'
    & $core --self-test $selfTest *> (Join-Path $evidence 'installed-self-test.log')
    if($LASTEXITCODE -ne 0){throw 'Installed self-test failed'}
    $check=Get-Content -LiteralPath $selfTest -Raw | ConvertFrom-Json
    if(-not $check.passed -or -not $check.workerStdioVerified -or $check.hardwareStarted){throw 'Installed self-test contract failed'}
    $guiResult=Join-Path $evidence 'installed-gui-smoke.json'
    $gui=Start-Process -FilePath $core -ArgumentList @('--smoke-test',('"'+$guiResult+'"')) -WindowStyle Hidden -Wait -PassThru
    if($gui.ExitCode -ne 0){throw 'Installed GUI process failed'}
    $check=Get-Content -LiteralPath $guiResult -Raw | ConvertFrom-Json
    if(-not $check.pageLoaded -or -not $check.uiReady -or $check.hardwareStarted){throw 'Installed GUI page did not initialize'}
    if((Get-FileHash -LiteralPath $profilePath -Algorithm SHA256).Hash -ne $profileHash){throw 'Application launch changed user mappings'}
    $uninstaller=Join-Path $installTarget 'unins000.exe'
    $uninstallLog=Join-Path $evidence 'uninstaller-smoke.log'
    $uninstall=Start-Process -FilePath $uninstaller -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/LOG="'+$uninstallLog+'"')) -WindowStyle Hidden -Wait -PassThru
    if($uninstall.ExitCode -ne 0){throw ('Uninstall failed: '+$uninstall.ExitCode)}
    if(Test-Path -LiteralPath $core){throw 'Installed core remains after uninstall'}
    if((Get-FileHash -LiteralPath $profilePath -Algorithm SHA256).Hash -ne $profileHash){throw 'Uninstall modified preserved mappings'}
    [ordered]@{installed=$true;reinstalled=$true;profilePreserved=$true;selfTestPassed=$true;guiReady=$true;uninstalled=$true;hardwareStarted=$false;target=$installTarget} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidence 'installer-smoke-result.json') -Encoding utf8
    Get-Content -LiteralPath (Join-Path $evidence 'installer-smoke-result.json')
} finally {
    $env:RC003_DATA_DIR=$oldData
}
