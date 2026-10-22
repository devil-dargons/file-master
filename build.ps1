# === 文件路径: build.ps1 ===
# FileMaster 一键打包：测试 -> PyInstaller(exe) -> Inno Setup(安装包)
# 用法：
#   powershell -File build.ps1              # 完整流程（先跑测试）
#   powershell -File build.ps1 -SkipTests   # 跳过测试直接打包
[CmdletBinding()]
param([switch]$SkipTests)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

$python    = Join-Path $root 'file_venv\Scripts\python.exe'
$iscc      = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
$exeOut    = Join-Path $root 'dist\FileMaster.exe'
$issScript = Join-Path $root 'installer\FileMaster.iss'
$outputDir = Join-Path $root 'installer\Output'
$sw = [System.Diagnostics.Stopwatch]::StartNew()

function Step([string]$msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# ---- 环境检查 ----
if (-not (Test-Path $python)) { throw "未找到虚拟环境 Python：$python" }
if (-not (Test-Path $iscc))   { throw "未找到 Inno Setup 编译器：$iscc （请先安装 Inno Setup 6）" }

# ---- 1. 测试 ----
if (-not $SkipTests) {
    Step '运行测试'
    & $python -m pytest tests -q
    if ($LASTEXITCODE -ne 0) { throw '测试未通过，已中止打包（可用 -SkipTests 跳过）' }
}

# ---- 2. 清理旧构建产物（installer\Output 保留历史版本，不清） ----
Step '清理 build/ 与 dist/'
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $root 'build')
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $root 'dist')

# ---- 3. PyInstaller 打 exe ----
Step 'PyInstaller 打包 exe'
& $python -m PyInstaller filemaster.spec --noconfirm
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $exeOut)) { throw 'PyInstaller 打包失败' }
$exeSize = '{0:N1} MB' -f ((Get-Item $exeOut).Length / 1MB)
Write-Host "exe 产物：$exeOut ($exeSize)"

# ---- 4. Inno Setup 打安装包 ----
Step 'Inno Setup 编译安装包'
& $iscc $issScript
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup 编译失败' }
$setup = Get-ChildItem $outputDir -Filter 'FileMaster-Setup-*.exe' |
         Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $setup) { throw '未找到生成的安装包' }

$setupSize = '{0:N1} MB' -f ($setup.Length / 1MB)
$elapsed = [math]::Round($sw.Elapsed.TotalSeconds)
Write-Host "`n打包完成（耗时 ${elapsed}s）" -ForegroundColor Green
Write-Host "安装包：$($setup.FullName) ($setupSize)" -ForegroundColor Green
