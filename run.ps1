# Simple launcher for DONNA services. Usage:
#   .\run.ps1 cortex        -> start cortex_memory_service on 8002
#   .\run.ps1 brain         -> start brain_orchestrator on 8001
#   .\run.ps1 research      -> start research_agent_service on 8003
#   .\run.ps1 channel       -> start channel_gateway_service on 8000
#   .\run.ps1 hostagent     -> start windows_host_agent on 8004
#   .\run.ps1 audio         -> start audio_stream_service on 8005
#   .\run.ps1 sentinel      -> start sentinel_service on 8006
#   .\run.ps1 autonomous    -> start autonomous_agent on 8007
#   .\run.ps1 smoke         -> run scripts\smoke_test.py (import check)
#   .\run.ps1 all           -> start all 8 services as background jobs
#   .\run.ps1 health        -> curl all /health endpoints
#   .\run.ps1 stop          -> stop all background jobs and free ports
#   .\run.ps1 kill-ports    -> force terminate any processes on ports 8000-8007

param(
    [Parameter(Mandatory=$true)]
    [string]$target
)

# Make sure venv is active (venv created via: uv venv)
if (-not $env:VIRTUAL_ENV) {
    Write-Host "venv is not active. Activating..." -ForegroundColor Yellow
    & .\.venv\Scripts\Activate.ps1
}

# Install/sync deps via: uv pip install -r <file>

switch ($target) {
    "cortex"     { python -m uvicorn services.cortex_memory_service.app:app --port 8002 }
    "brain"      { python -m uvicorn services.brain_orchestrator.app:app --port 8001 }
    "research"   { python -m uvicorn services.research_agent_service.app:app --port 8003 }
    "channel"    { python -m uvicorn services.channel_gateway_service.app:app --port 8000 }
    "hostagent"  { python -m uvicorn services.windows_host_agent.app:app --port 8004 }
    "audio"      { python services\audio_stream_service\app.py }
    "sentinel"   { python -m uvicorn services.sentinel_service.app:app --port 8006 }
    "autonomous" { python -m uvicorn services.autonomous_agent.app:app --port 8007 }
    "smoke"      { python scripts\smoke_test.py }
    "all" {
        Write-Host "Starting all 8 services in background..." -ForegroundColor Cyan
        Start-Job -Name "sentinel"   { Set-Location $using:PWD; .\.venv\Scripts\Activate.ps1; python -m uvicorn services.sentinel_service.app:app --port 8006 }
        Start-Sleep -Seconds 1
        Start-Job -Name "cortex"     { Set-Location $using:PWD; .\.venv\Scripts\Activate.ps1; python -m uvicorn services.cortex_memory_service.app:app --port 8002 }
        Start-Job -Name "brain"      { Set-Location $using:PWD; .\.venv\Scripts\Activate.ps1; python -m uvicorn services.brain_orchestrator.app:app --port 8001 }
        Start-Job -Name "research"   { Set-Location $using:PWD; .\.venv\Scripts\Activate.ps1; python -m uvicorn services.research_agent_service.app:app --port 8003 }
        Start-Job -Name "channel"    { Set-Location $using:PWD; .\.venv\Scripts\Activate.ps1; python -m uvicorn services.channel_gateway_service.app:app --port 8000 }
        Start-Job -Name "hostagent"  { Set-Location $using:PWD; .\.venv\Scripts\Activate.ps1; python -m uvicorn services.windows_host_agent.app:app --port 8004 }
        Start-Job -Name "autonomous" { Set-Location $using:PWD; .\.venv\Scripts\Activate.ps1; python -m uvicorn services.autonomous_agent.app:app --port 8007 }
        Start-Job -Name "audio"      { Set-Location $using:PWD; .\.venv\Scripts\Activate.ps1; python services\audio_stream_service\app.py }
        Write-Host "Waiting 3 seconds for startup..." -ForegroundColor Cyan
        Start-Sleep -Seconds 3
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
            $conns = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
            foreach ($c in $conns) {
                if ($c.OwningProcess -gt 0 -and $c.OwningProcess -ne $PID) {
                    Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
                }
            }
        }
        Write-Host "All background services and ports stopped." -ForegroundColor Cyan
    }
    "kill-ports" {
        $ports = @(8000, 8001, 8002, 8003, 8004, 8005, 8006, 8007)
        foreach ($p in $ports) {
            $conns = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
            foreach ($c in $conns) {
                if ($c.OwningProcess -gt 0 -and $c.OwningProcess -ne $PID) {
                    Write-Host "Stopping process PID $($c.OwningProcess) on port $p..." -ForegroundColor Yellow
                    Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
                }
            }
        }
        Write-Host "All DONNA ports (8000-8007) cleared." -ForegroundColor Green
    }
    "health" {
        $ports = @{sentinel=8006; cortex=8002; brain=8001; research=8003; channel=8000; hostagent=8004; audio=8005; autonomous=8007}
        foreach ($name in $ports.Keys) {
            $port = $ports[$name]
            $healthPath = "/health"
            if ($name -eq "channel") { $healthPath = "/gateway/health" }
            try {
                $r = Invoke-RestMethod -Uri "http://localhost:$port$healthPath" -TimeoutSec 2
                $json = $r | ConvertTo-Json -Compress
                Write-Host "OK   [${name}:${port}] $json" -ForegroundColor Green
            } catch {
                Write-Host "FAIL [${name}:${port}] unreachable" -ForegroundColor Red
            }
        }
    }
    default { Write-Host "Unknown target: $target" -ForegroundColor Red }
}