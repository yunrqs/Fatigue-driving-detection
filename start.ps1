param([switch]$BackendOnly)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

# The CMD wrapper keeps any setup error visible when launched by double-click.
& (Join-Path $PSScriptRoot 'setup.ps1') -BackendOnly:$BackendOnly
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

function Test-BackendHealth {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8001/api/health' -TimeoutSec 2
        return $health.ok -eq $true
    } catch { return $false }
}

function Stop-BackendProcess {
    param($Process)
    if (-not $Process) { return }
    if ($Process.HasExited) { return }
    # The process we hold is the cmd.exe wrapper, and python.exe is its child.
    # /T kills the whole tree so the port is actually released; /F skips the confirmation prompt.
    & taskkill.exe /T /F /PID $Process.Id 2>&1 | Out-Null
}

if (-not (Test-BackendHealth)) {
    $backendPython = Join-Path $PSScriptRoot 'backend\.venv\Scripts\python.exe'
    $pythonExe = $backendPython

    Write-Host "Backend Python: $pythonExe"
    $logDir = Join-Path $PSScriptRoot 'backend\outputs\dev'
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    $stdoutLog = Join-Path $logDir 'backend.stdout.log'
    $stderrLog = Join-Path $logDir 'backend.stderr.log'

    # Deliberately NOT using Start-Process. Windows PowerShell 5.1 rebuilds the environment into
    # a case-insensitive dictionary there and throws ArgumentException ("item already added:
    # key HTTPS_PROXY, key being added https_proxy") whenever the block holds both casings of a
    # variable. Proxy clients and Git Bash routinely set both, so on those machines the backend
    # never started at all. -UseNewEnvironment does NOT avoid it (verified on this machine).
    # ProcessStartInfo passes the environment through untouched.
    #
    # cmd.exe does the redirection so the log file handles belong to the child, not to us:
    # this script exits right away under -BackendOnly and the service must keep logging.
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = if ($env:ComSpec) { $env:ComSpec } else { 'cmd.exe' }
    $startInfo.Arguments = '/d /s /c ""{0}" -m backend.src.server 1>"{1}" 2>"{2}""' -f $pythonExe, $stdoutLog, $stderrLog
    $startInfo.WorkingDirectory = $PSScriptRoot
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $backendProcess = New-Object System.Diagnostics.Process
    $backendProcess.StartInfo = $startInfo
    if (-not $backendProcess.Start()) { throw 'Failed to launch the backend process.' }

    $healthy = $false
    for ($attempt = 0; $attempt -lt 120; $attempt++) {
        if (Test-BackendHealth) { $healthy = $true; break }
        if ($backendProcess.HasExited) { break }
        Start-Sleep -Milliseconds 500
    }
    if (-not $healthy) {
        Stop-BackendProcess $backendProcess
        if (Test-Path -LiteralPath $stderrLog) { Get-Content -LiteralPath $stderrLog -Tail 30 }
        throw "Backend did not become ready. See $stderrLog"
    }
    Write-Host "Backend started (PID $($backendProcess.Id)). Logs: $logDir"
} else {
    Write-Host 'Backend is already running.'
}

Write-Host 'Backend health OK: http://127.0.0.1:8001/api/health'
if (-not $BackendOnly) {
    # Resolve npm the same way setup.ps1 does instead of hardcoding npm.cmd: some Node
    # distributions only ship npm.exe or a .ps1 shim.
    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npmCommand) { $npmCommand = Get-Command npm -ErrorAction SilentlyContinue }
    if (-not $npmCommand) {
        Stop-BackendProcess $backendProcess
        throw 'npm was not found. Install Node.js 20.19+ or 22.12+, then reopen this script.'
    }

    Write-Host 'Starting frontend: http://127.0.0.1:5173'
    Write-Host 'Keep this window open. Press Ctrl+C to stop the frontend.'
    # Default to non-zero: even if npm fails to launch and $LASTEXITCODE is never set,
    # a failure cannot be reported as success.
    $frontendExitCode = 1
    try {
        & $npmCommand.Source --prefix web-react run dev -- --open
        $frontendExitCode = $LASTEXITCODE
    } finally {
        # Only stop the backend started by this invocation, never a reused service.
        Stop-BackendProcess $backendProcess
    }
    exit $frontendExitCode
}
