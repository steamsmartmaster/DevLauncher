# DevLauncher Windows 单文件版构建脚本（仓库根运行）
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1
# 产物：dist\DevLauncher.exe、dist\DevLauncher-b1.1-win64.zip
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# 1) 图标：ui/icon.ico 缺失（或想刷新）时从 SVG 生成
if (-not (Test-Path 'ui\icon.ico')) {
    python tools\make_icon.py
    if ($LASTEXITCODE -ne 0) { throw 'make_icon.py failed' }
}

# 2) PyInstaller onefile 窗口版：自定义图标 + 版本资源
python -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name DevLauncher `
    --icon ui\icon.ico `
    --version-file version_info.txt `
    --add-data "ui;ui" `
    main.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

# 3) 组装发布 zip：exe + 全部插件（frozen 时从 exe 同目录取 plugins/）+ 更新日志
$tag = 'b1.2'
$zipName = "DevLauncher-$tag-win64.zip"
$stage = Join-Path $env:TEMP "devlauncher-build-$tag"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path "$stage\plugins" -Force | Out-Null
Copy-Item 'dist\DevLauncher.exe' "$stage\"
foreach ($plug in (Get-ChildItem 'plugins' -Directory)) {
    $dst = Join-Path "$stage\plugins" $plug.Name
    New-Item -ItemType Directory -Path $dst -Force | Out-Null
    Copy-Item (Join-Path $plug.FullName '*') $dst -Recurse -Force
}
Copy-Item 'CHANGELOG.txt' "$stage\"
$zipPath = Join-Path 'dist' $zipName
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path "$stage\*" -DestinationPath $zipPath

# 4) 冒烟：30s 存活 + 日志增量含启动完成标记（只验存活会放过"异常对话框挂着"的假活）
$exePath = (Resolve-Path 'dist\DevLauncher.exe').Path
$logPath = 'dist\logs\launcher.log'
$ok = $false
for ($try = 1; $try -le 3 -and -not $ok; $try++) {
    $beforeLen = if (Test-Path $logPath) { (Get-Item $logPath).Length } else { 0 }
    $p = Start-Process -FilePath $exePath -PassThru
    Start-Sleep -Seconds 30
    $alive = $false
    if ($null -ne $p) {
        $p.Refresh()
        $alive = -not $p.HasExited
        $code = if ($p.HasExited) { $p.ExitCode } else { '-' }
    } else { $code = 'spawn-failed' }
    python tools\smoke_check.py $logPath $beforeLen
    $booted = ($LASTEXITCODE -eq 0)
    if ($alive -and $booted) {
        $ok = $true
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
    } else {
        Write-Output "smoke try${try} failed (alive=$alive exit=$code booted=$booted), retrying..."
        if ($alive) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 5
    }
}
if (-not $ok) { throw 'smoke failed 3 times' }
Get-Process | Where-Object { $_.ProcessName -like '*DevLauncher*' -or $_.ProcessName -like '*QtWebEngine*' } |
    ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }

Write-Output "BUILD OK: dist\DevLauncher.exe + dist\$zipName"
