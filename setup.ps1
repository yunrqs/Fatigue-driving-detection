param(
    [switch]$BackendOnly,
    [switch]$Reinstall
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed (exit $LASTEXITCODE): $Program $($Arguments -join ' ')"
    }
}

function Test-Python {
    param([string]$Program, [string[]]$Prefix = @())
    try {
        & $Program @Prefix -c 'import sys, struct; sys.exit(0 if sys.version_info >= (3, 10) and struct.calcsize(''P'') == 8 else 1)' 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    } catch { return $false }
}

function Test-BackendImports {
    # Two stages so an error tells you whether the server stack or the data pipeline is broken.
    # The second stage imports mind_wandering.training.train, which pulls pandas / sklearn /
    # joblib / matplotlib at module level. That module has no import-time side effects.
    & $pythonExe -c 'import fastapi, uvicorn, python_multipart, numpy, cv2, torch, torchvision, mediapipe; import backend.src.app' | Out-Host
    if ($LASTEXITCODE -ne 0) { return $false }
    & $pythonExe -c 'import pandas, sklearn, joblib, tqdm, matplotlib; import backend.src.mind_wandering.training.train' | Out-Host
    return $LASTEXITCODE -eq 0
}

try {
    $requirements = Join-Path $PSScriptRoot 'backend\requirements.txt'
    $model = Join-Path $PSScriptRoot 'backend\models\emotion\fer2013_best_model.pth'
    foreach ($file in @($requirements, $model)) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
            throw "Required file is missing: $file. Extract the complete project, including backend/models/emotion."
        }
    }

    # Check prerequisites before downloading large Python packages.
    if (-not $BackendOnly) {
        $nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
        $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if (-not $nodeCommand -or -not $npmCommand) {
            throw 'Node.js and npm were not found. Install Node.js 20.19+ or 22.12+ (with npm), then reopen this script.'
        }
        # Match Vite's own engines range (^20.19.0 || >=22.12.0) instead of requiring 22.12+.
        & $nodeCommand.Source -e 'const v=process.versions.node.split(''.'').map(Number); process.exit(v[0]>22 || (v[0]===22 && v[1]>=12) || (v[0]===20 && v[1]>=19) ? 0 : 1)'
        if ($LASTEXITCODE -ne 0) {
            throw "Node.js $(& $nodeCommand.Source --version) is not supported. Install Node.js 20.19+ or 22.12+ (with npm), then reopen this script."
        }
        foreach ($file in @('web-react\package.json', 'web-react\package-lock.json', 'web-react\public\mediapipe\face_mesh\face_mesh.js')) {
            if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $file) -PathType Leaf)) {
                throw "Required frontend file is missing: $file. Extract the complete project."
            }
        }
    }

    $venvDir = Join-Path $PSScriptRoot 'backend\.venv'
    $pythonExe = Join-Path $venvDir 'Scripts\python.exe'
    if (Test-Path -LiteralPath $venvDir) {
        if (-not (Test-Path -LiteralPath $pythonExe) -or -not (Test-Python $pythonExe)) {
            throw "The virtual environment is unusable. Rename $venvDir and rerun setup.cmd. Do not copy virtual environments between computers."
        }
    } else {
        $basePython = $null
        $prefix = @()
        $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($launcher) {
            foreach ($version in @('-3.11', '-3.12', '-3.13', '-3.10', '-3')) {
                if (Test-Python $launcher.Source @($version)) {
                    $basePython = $launcher.Source
                    $prefix = @($version)
                    break
                }
            }
        }
        if (-not $basePython) {
            $command = Get-Command python.exe -ErrorAction SilentlyContinue
            if ($command -and (Test-Python $command.Source)) { $basePython = $command.Source }
        }
        if (-not $basePython) {
            throw '64-bit Python 3.10+ was not found. Install Python (3.11 recommended), enable Add Python to PATH, then reopen this script.'
        }
        Write-Host '[1/3] Creating isolated Python environment: backend\.venv'
        Invoke-Checked $basePython ($prefix + @('-m', 'venv', $venvDir))
    }

    $pythonVersion = (& $pythonExe --version 2>&1 | Out-String).Trim()
    $backendStamp = Join-Path $venvDir '.focuslens-requirements.txt'
    # Compare dependency content, not the project path: moving the checkout does not invalidate the venv.
    $backendKey = "$pythonVersion|$((Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash)"
    $backendCurrent = (Test-Path -LiteralPath $backendStamp) -and ((Get-Content -LiteralPath $backendStamp -Raw).Trim() -eq $backendKey)
    $installBackend = $Reinstall -or -not $backendCurrent
    if ($installBackend) {
        # Delete the stamp instead of writing an empty string: an empty write leaves only a BOM,
        # which makes "did the install finish" ambiguous. A missing file is an unambiguous signal.
        Remove-Item -LiteralPath $backendStamp -Force -ErrorAction SilentlyContinue
        Write-Host '[2/3] Installing backend dependencies. The first download may take several minutes.'
        & $pythonExe -m pip --version *> $null
        if ($LASTEXITCODE -ne 0) { Invoke-Checked $pythonExe @('-m', 'ensurepip', '--upgrade') }
        # --retries/--timeout let flaky connections recover instead of starting the whole install over.
        Invoke-Checked $pythonExe @('-m', 'pip', 'install', '--retries', '5', '--timeout', '60', '-r', $requirements)
        if (-not (Test-BackendImports)) {
            # mediapipe's matplotlib import can fail transiently; retry once before giving up.
            Write-Host 'Backend import check failed once, retrying...'
            if (-not (Test-BackendImports)) { throw 'Backend dependency validation failed. See the import error above.' }
        }
        Set-Content -LiteralPath $backendStamp -Value $backendKey -Encoding UTF8
    } else {
        Write-Host '[2/3] Backend dependencies are ready.'
    }

    # backend/models/ is git-ignored, so a fresh clone has no dlib landmark model.
    # Fetch it here instead of at "start" time, where a 100 MB download would look like a hang.
    # Failure is not fatal: the app retries the download when the session starts.
    Write-Host 'Checking model assets: dlib 68-point landmark predictor.'
    & $pythonExe -c "from backend.src.config.model_assets import resolve_face_predictor; print('Ready:', resolve_face_predictor())" | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Warning: the dlib landmark model could not be prepared. Clicking Start will retry the download.' -ForegroundColor Yellow
    }

    if (-not $BackendOnly) {
        $frontendDir = Join-Path $PSScriptRoot 'web-react'
        $frontendStamp = Join-Path $frontendDir 'node_modules\.focuslens-dependencies.txt'
        $nodeVersion = & $nodeCommand.Source --version
        $packageHash = (Get-FileHash -LiteralPath (Join-Path $frontendDir 'package.json') -Algorithm SHA256).Hash
        $lockHash = (Get-FileHash -LiteralPath (Join-Path $frontendDir 'package-lock.json') -Algorithm SHA256).Hash
        $frontendKey = "$nodeVersion|$packageHash|$lockHash"
        $frontendCurrent = (Test-Path -LiteralPath $frontendStamp) -and ((Get-Content -LiteralPath $frontendStamp -Raw).Trim() -eq $frontendKey)
        if ($Reinstall -or -not $frontendCurrent -or -not (Test-Path -LiteralPath (Join-Path $frontendDir 'node_modules\.bin\vite.cmd'))) {
            Write-Host '[3/3] Installing frontend dependencies.'
            # Same convention as the backend stamp: absence of the file marks an interrupted install.
            Remove-Item -LiteralPath $frontendStamp -Force -ErrorAction SilentlyContinue
            Invoke-Checked $npmCommand.Source @('--prefix', $frontendDir, 'ci', '--include=dev', '--no-audit', '--no-fund')
            Set-Content -LiteralPath $frontendStamp -Value $frontendKey -Encoding UTF8
        } else {
            Write-Host '[3/3] Frontend dependencies are ready.'
        }
    }
    Write-Host "Environment ready: $pythonExe"
    exit 0
} catch {
    Write-Host "Setup failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
