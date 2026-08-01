param(
    [string]$ApiBaseUrl = 'http://localhost:8000',
    [string]$FrontendUrl = 'http://localhost:5173',
    [int]$TimeoutSeconds = 10
)

$ErrorActionPreference = 'Stop'
$failures = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()

function Write-Check([string]$Name, [bool]$Passed, [string]$Detail) {
    $label = if ($Passed) { 'PASS' } else { 'FAIL' }
    $color = if ($Passed) { 'Green' } else { 'Red' }
    Write-Host ("[{0}] {1}: {2}" -f $label, $Name, $Detail) -ForegroundColor $color
    if (-not $Passed) { $failures.Add("${Name}: ${Detail}") }
}

function Get-Json([string]$Path) {
    Invoke-RestMethod -Uri "${ApiBaseUrl}${Path}" -TimeoutSec $TimeoutSeconds
}

Write-Host 'LineageGuard five-minute demo preflight' -ForegroundColor Cyan

try {
    $running = @(docker compose ps --services --status running 2>$null)
    foreach ($service in @('backend', 'frontend', 'qdrant')) {
        Write-Check "container/${service}" ($running -contains $service) 'expected running Compose service'
    }
} catch {
    Write-Check 'Docker Compose' $false 'docker compose is unavailable'
}

try {
    $frontend = Invoke-WebRequest -Uri $FrontendUrl -UseBasicParsing -TimeoutSec $TimeoutSeconds
    Write-Check 'frontend' ($frontend.StatusCode -eq 200) "HTTP $($frontend.StatusCode)"
} catch {
    Write-Check 'frontend' $false $_.Exception.Message
}

try {
    $health = Get-Json '/api/v1/health'
    Write-Check 'API' ($health.status -eq 'ok') "status=$($health.status)"
    Write-Check 'DataHub configuration' ($health.datahub -eq 'configured') "state=$($health.datahub)"
    Write-Check 'Qdrant configuration' ($health.qdrant -eq 'configured') "state=$($health.qdrant)"

    foreach ($name in @('chat', 'nvidia_critic', 'openai_judge', 'groq_judge')) {
        $provider = $health.providers.$name
        if ($null -eq $provider -or -not $provider.available) {
            $reason = if ($null -eq $provider) { 'readiness not reported' } else { $provider.reason }
            $warnings.Add("${name}: ${reason}")
            Write-Host "[OPTIONAL] ${name}: DISABLED - ${reason}" -ForegroundColor Yellow
        } else {
            Write-Host "[OPTIONAL] ${name}: CONFIGURED - $($provider.model)" -ForegroundColor Green
        }
    }
} catch {
    Write-Check 'health endpoint' $false $_.Exception.Message
}

try {
    $catalog = Get-Json '/api/v1/datahub/catalog/cache'
    $assetCount = @($catalog.graph.nodes).Count
    $edgeCount = @($catalog.graph.edges).Count
    Write-Check '3D catalog cache' ($assetCount -gt 0 -and $edgeCount -gt 0) "state=$($catalog.status.state), assets=${assetCount}, relations=${edgeCount}"
    if ($catalog.status.refresh_in_progress) {
        $warnings.Add('Catalog enrichment is running; the existing graph is safe to show, but do not trigger another refresh.')
    }
} catch {
    Write-Check '3D catalog cache' $false $_.Exception.Message
}

try {
    $rag = Get-Json '/api/v1/chat/index/status'
    Write-Check 'RAG query path' ($rag.query_available -eq $true) "state=$($rag.state), indexed=$($rag.indexed_assets)/$($rag.total_assets)"
} catch {
    Write-Check 'RAG query path' $false $_.Exception.Message
}

if ($warnings.Count -gt 0) {
    Write-Host "`nOptional warnings:" -ForegroundColor Yellow
    $warnings | ForEach-Object { Write-Host "- $_" -ForegroundColor Yellow }
}

if ($failures.Count -gt 0) {
    Write-Host "`nDEMO NOT READY: $($failures.Count) required check(s) failed." -ForegroundColor Red
    exit 1
}

Write-Host "`nDEMO READY: core read-only path is available." -ForegroundColor Green
Write-Host 'Use docs/five-minute-demo.md. Skip only optional provider steps reported as DISABLED.'
