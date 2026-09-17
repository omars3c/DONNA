# Simple launcher for DONNA services. Usage:
#   .\run.ps1 cortex        -> start cortex_memory_service on 8002
#   .\run.ps1 brain         -> start brain_orchestrator on 8001
#   .\run.ps1 research      -> start research_agent_service on 8003
#   .\run.ps1 channel       -> start channel_gateway_service on 8000
#   .\run.ps1 hostagent     -> start windows_host_agent on 8004
#   .\run.ps1 audio         -> start audio_stream_service on 8005
#   .\run.ps1 sentinel      -> start sentinel_service on 8006
#   .\run.ps1 autonomous    -> start autonomous_agent on 8007
#   .\run.ps1 orchestrator  -> launch unified supervisor (run_microservices.py)
#   .\run.ps1 smoke         -> run scripts\smoke_test.py (import check)
#   .\run.ps1 all           -> start all 8 services as background jobs
#   .\run.ps1 health        -> check health of all endpoints via 127.0.0.1
#   .\run.ps1 stop          -> stop all background jobs and free ports
#   .\run.ps1 kill-ports    -> force terminate any processes on ports 8000-8007

param(
    [Parameter(Mandatory=$true)]
    [string]$target
)

$pyExe = Join-Path $PWD ".venv\Scripts\python.exe"
if (-not (Test-Path $pyExe)) {
    $pyExe = "python"
}

# Make sure venv is active in current shell if possible
if (-not $env:VIRTUAL_ENV) {
    if (Test-Path ".\.venv\Scripts\Activate.ps1") {
        try {
            & .\.venv\Scripts\Activate.ps1
        } catch {
            # ExecutionPolicy might restrict script activation; pyExe will still be used directly
        }
    }
}

function Free-Port([int]$p) {
    $conns = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        if ($c.OwningProcess -gt 0 -and $c.OwningProcess -ne $PID) {
            Write-Host "Freeing port $p (stopping PID $($c.OwningProcess))..." -ForegroundColor Yellow
            Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    }
}

switch ($target) {
    "cortex"       { Free-Port 8002; & $pyExe -m services.cortex_memory_service.app }
    "brain"        { Free-Port 8001; & $pyExe -m services.brain_orchestrator.app }
    "research"     { Free-Port 8003; & $pyExe -m services.research_agent_service.app }
    "channel"      { Free-Port 8000; & $pyExe -m services.channel_gateway_service.app }
    "hostagent"    { Free-Port 8004; & $pyExe -m services.windows_host_agent.app }
    "audio"        { Free-Port 8005; & $pyExe -m services.audio_stream_service.app }
    "sentinel"     { Free-Port 8006; & $pyExe -m services.sentinel_service.app }
    "autonomous"   { Free-Port 8007; & $pyExe -m services.autonomous_agent.app }
    "orchestrator" { & $pyExe run_microservices.py }
    "smoke"        { & $pyExe scripts\smoke_test.py }
    "all" {
        Write-Host "Ensuring all DONNA ports (8000-8007) are free..." -ForegroundColor Cyan
        @(8000, 8001, 8002, 8003, 8004, 8005, 8006, 8007) | ForEach-Object { Free-Port $_ }

        Write-Host "Starting all 8 services in background..." -ForegroundColor Cyan
        Start-Job -Name "sentinel"   -ArgumentList $PWD, $pyExe -ScriptBlock { param($dir, $py) Set-Location $dir; & $py -m services.sentinel_service.app }
        Start-Sleep -Seconds 1
        Start-Job -Name "cortex"     -ArgumentList $PWD, $pyExe -ScriptBlock { param($dir, $py) Set-Location $dir; & $py -m services.cortex_memory_service.app }
        Start-Job -Name "brain"      -ArgumentList $PWD, $pyExe -ScriptBlock { param($dir, $py) Set-Location $dir; & $py -m services.brain_orchestrator.app }
        Start-Job -Name "research"   -ArgumentList $PWD, $pyExe -ScriptBlock { param($dir, $py) Set-Location $dir; & $py -m services.research_agent_service.app }
        Start-Job -Name "channel"    -ArgumentList $PWD, $pyExe -ScriptBlock { param($dir, $py) Set-Location $dir; & $py -m services.channel_gateway_service.app }
        Start-Job -Name "hostagent"  -ArgumentList $PWD, $pyExe -ScriptBlock { param($dir, $py) Set-Location $dir; & $py -m services.windows_host_agent.app }
        Start-Job -Name "autonomous" -ArgumentList $PWD, $pyExe -ScriptBlock { param($dir, $py) Set-Location $dir; & $py -m services.autonomous_agent.app }
        Start-Job -Name "audio"      -ArgumentList $PWD, $pyExe -ScriptBlock { param($dir, $py) Set-Location $dir; & $py -m services.audio_stream_service.app }

        Write-Host "Waiting 8 seconds for services to initialize..." -ForegroundColor Cyan
        Start-Sleep -Seconds 8
        Get-Job
        Write-Host "`nNext: .\run.ps1 health   (same window)" -ForegroundColor Yellow
        Write-Host "View one job's logs:  Receive-Job -Name cortex" -ForegroundColor Yellow
        Write-Host "Stop everything:      .\run.ps1 stop" -ForegroundColor Yellow
    }
    "stop" {
        Get-Job | Stop-Job -ErrorAction SilentlyContinue
        Get-Job | Remove-Job -ErrorAction SilentlyContinue
        $ports = @(8000, 8001, 8002, 8003, 8004, 8005, 8006, 8007)
        foreach ($p in $ports) {
            Free-Port $p
        }
        Write-Host "All background services and ports stopped." -ForegroundColor Cyan
    }
    "kill-ports" {
        $ports = @(8000, 8001, 8002, 8003, 8004, 8005, 8006, 8007)
        foreach ($p in $ports) {
            Free-Port $p
        }
        Write-Host "All DONNA ports (8000-8007) cleared." -ForegroundColor Green
    }
    "health" {
        $ports = @{
            sentinel   = 8006
            cortex     = 8002
            brain      = 8001
            research   = 8003
            channel    = 8000
            hostagent  = 8004
            audio      = 8005
            autonomous = 8007
        }
        foreach ($name in $ports.Keys) {
            $port = $ports[$name]
            $healthPath = "/health"
            if ($name -eq "channel") { $healthPath = "/gateway/health" }
            $ok = $false
            for ($i = 0; $i -lt 4; $i++) {
                try {
                    $r = Invoke-RestMethod -Uri "http://127.0.0.1:$port$healthPath" -TimeoutSec 3
                    $json = $r | ConvertTo-Json -Compress
                    Write-Host "OK   [${name}:${port}] $json" -ForegroundColor Green
                    $ok = $true
                    break
                } catch {
                    if ($name -eq "channel" -and $healthPath -eq "/gateway/health") {
                        $healthPath = "/health"
                    }
                    Start-Sleep -Milliseconds 800
                }
            }
            if (-not $ok) {
                Write-Host "FAIL [${name}:${port}] unreachable" -ForegroundColor Red
            }
        }
    }
    default { Write-Host "Unknown target: $target" -ForegroundColor Red }
}