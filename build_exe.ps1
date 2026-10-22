# DevLauncher Windows 打包构建脚本（双击可运行）
#   powershell -ExecutionPolicy Bypass -File build_exe.ps1
# 产物：dist\DevLauncher\（onedir 目录）+ dist\DevLauncher-b1.2.1-win64.zip
#
# 用 --onedir 而非 --onefile：onefile 每次启动都要把 ~200MB 解包到
# %TEMP%\_MEI*，实测冷启动 8s；onedir 免去解包，冷启动约 2s。
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# 1) 图标：ui/icon.ico 缺失则即时刷新（SVG 转）
if (-not (Test-Path 'ui\icon.ico')) {
    python tools\make_icon.py
    if ($LASTEXITCODE -ne 0) { throw 'make_icon.py failed' }
}

# 2) PyInstaller onedir 打包：入口 boot.py（先显示启动画面再导入重量级模块）
python -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name DevLauncher `
    --icon ui\icon.ico `
    --version-file version_info.txt `
    --add-data "ui;ui" `
    boot.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

# build\ 下是中间产物：同名 stub 没有 _internal\ 依赖，双击会报
# Failed to load Python DLL；删掉它并留说明，避免误运行。
$stub = 'build\DevLauncher\DevLauncher.exe'
if (Test-Path $stub) { Remove-Item $stub -Force }
Set-Content -LiteralPath 'build\DevLauncher\README-build.txt' -Value '这是 PyInstaller 构建中间目录，程序不可直接运行。可运行版在 dist\DevLauncher\DevLauncher.exe。' -Encoding UTF8

# 3) 组装发布 zip：整个 onedir 目录 + 插件 + 更新日志
$tag = 'b1.2.1'
$zipName = "DevLauncher-$tag-win64.zip"
$stage = Join-Path $env:TEMP "devlauncher-build-$tag"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path "$stage\DevLauncher" -Force | Out-Null
Copy-Item 'dist\DevLauncher\*' "$stage\DevLauncher\" -Recurse -Force
New-Item -ItemType Directory -Path "$stage\DevLauncher\plugins" -Force | Out-Null
foreach ($plug in (Get-ChildItem 'plugins' -Directory)) {
    $dst = Join-Path "$stage\DevLauncher\plugins" $plug.Name
    New-Item -ItemType Directory -Path $dst -Force | Out-Null
    Copy-Item (Join-Path $plug.FullName '*') $dst -Recurse -Force
}
Copy-Item 'CHANGELOG.txt' "$stage\DevLauncher\"
Get-ChildItem "$stage\DevLauncher\plugins" -Directory | ForEach-Object {
    $pyc = Join-Path $_.FullName '__pycache__'
    if (Test-Path $pyc) { Remove-Item $pyc -Recurse -Force }
}
$zipPath = Join-Path 'dist' $zipName
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path "$stage\DevLauncher" -DestinationPath $zipPath

# 4) 冒烟：30s 存活 + 日志启动标记（只认「异常对话框未弹出」以外的假活）
$exePath = (Resolve-Path 'dist\DevLauncher\DevLauncher.exe').Path
$logPath = 'dist\DevLauncher\logs\launcher.log'
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

Write-Output "BUILD OK: dist\DevLauncher\DevLauncher.exe + dist\$zipName"
