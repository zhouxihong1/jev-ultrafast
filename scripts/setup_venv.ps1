# Create .venv and install Jev Ultrafast reproducibly (Windows PowerShell).
#
#   powershell -ExecutionPolicy Bypass -File scripts/setup_venv.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/setup_venv.ps1 -NoDev
#   powershell -ExecutionPolicy Bypass -File scripts/setup_venv.ps1 -Exact -Recreate
#   powershell -ExecutionPolicy Bypass -File scripts/setup_venv.ps1 -Mirror https://pypi.tuna.tsinghua.edu.cn/simple
#
# -Exact is what makes a machine reproduce another machine: requirements.lock.txt pins the
# full dependency graph, not just the two direct dependencies.
param(
    [string]$Python = "",
    [string]$Mirror = $env:JEV_PIP_MIRROR,
    [switch]$NoDev,
    [switch]$Exact,
    [switch]$Recreate
)

$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Venv = Join-Path $Repo ".venv"
$VenvPython = Join-Path $Venv "Scripts\python.exe"

function Find-Python {
    $candidates = @()
    if ($Python) { $candidates += $Python }
    $candidates += @("python", "python3", "py")
    foreach ($candidate in $candidates) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        & $candidate -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { return $candidate }
    }
    return $null
}

$base = Find-Python
if (-not $base) { throw "No Python >= 3.12 found. Install one, or pass -Python C:\path\to\python.exe" }

if ($Recreate -and (Test-Path $Venv)) {
    Write-Host "==> removing $Venv"
    Remove-Item -LiteralPath $Venv -Recurse -Force
}

if (-not (Test-Path $Venv)) {
    Write-Host "==> creating venv at $Venv"
    & $base -m venv $Venv
}

$pipArgs = @()
if ($Mirror) { $pipArgs += @("--index-url", $Mirror) }

Write-Host "==> upgrading pip"
& $VenvPython -m pip install --upgrade pip @pipArgs --quiet

$lock = Join-Path $Repo "requirements.lock.txt"
if ($Exact -and (Test-Path $lock)) {
    Write-Host "==> installing exact pins from requirements.lock.txt"
    & $VenvPython -m pip install @pipArgs -r $lock
} elseif ($NoDev) {
    Write-Host "==> installing requirements.txt"
    & $VenvPython -m pip install @pipArgs -r (Join-Path $Repo "requirements.txt")
} else {
    Write-Host "==> installing requirements-dev.txt"
    & $VenvPython -m pip install @pipArgs -r (Join-Path $Repo "requirements-dev.txt")
}

Write-Host "==> installing jev-ultrafast in editable mode"
& $VenvPython -m pip install @pipArgs --no-deps -e $Repo
if ($LASTEXITCODE -ne 0) {
    Write-Host "    editable install failed; run the CLI as: python -m jev_ultrafast.cli run \"...\""
}

$envFile = Join-Path $Repo ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item (Join-Path $Repo ".env.example") $envFile
    Write-Host "==> created .env from .env.example - add TYPESAFE_API_KEY and TEXT_MODEL_API_KEY"
}

Write-Host ""
Write-Host "==> environment check"
& $VenvPython -m jev_ultrafast.cli doctor
Write-Host ""
Write-Host "Done. Activate with:  .\.venv\Scripts\Activate.ps1"
Write-Host ""
Write-Host "Next:"
Write-Host "  1. jev-browser start        # a browser the harness can drive"
Write-Host "  2. jev-selftest             # prove the stack, no API key needed"
Write-Host "  3. <edit .env>              # then add TYPESAFE_API_KEY and TEXT_MODEL_API_KEY"
Write-Host "  4. jev-run `"baidu search shanghai weather`""
