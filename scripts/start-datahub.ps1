param(
    [switch]$SkipDatapack,
    [switch]$RefreshCompose
)

$ErrorActionPreference = 'Stop'

$quickstartDirectory = Join-Path $env:USERPROFILE '.datahub\quickstart'
$quickstartCompose = Join-Path $quickstartDirectory 'docker-compose.yml'
New-Item -ItemType Directory -Force -Path $quickstartDirectory | Out-Null

if ($RefreshCompose -or -not (Test-Path $quickstartCompose)) {
    # PowerShell uses the Windows certificate store. This keeps TLS verification enabled
    # on corporate networks where Python's bundled CA store does not include the proxy CA.
    Invoke-WebRequest `
        -Uri 'https://raw.githubusercontent.com/datahub-project/datahub/v1.6.0/docker/quickstart/docker-compose.quickstart-profile.yml' `
        -OutFile $quickstartCompose
}

$localSecrets = Join-Path $quickstartDirectory '.local-secrets.env'
if (-not (Test-Path $localSecrets)) {
    function New-LocalSecret {
        $bytes = New-Object byte[] 32
        $random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $random.GetBytes($bytes)
        } finally {
            $random.Dispose()
        }
        [Convert]::ToBase64String($bytes)
    }

    @(
        '# Auto-generated local development secrets. Do not commit this file.',
        "DATAHUB_TOKEN_SERVICE_SIGNING_KEY=$(New-LocalSecret)",
        "DATAHUB_TOKEN_SERVICE_SALT=$(New-LocalSecret)"
    ) | Set-Content -Path $localSecrets -Encoding utf8
}

Get-Content $localSecrets | ForEach-Object {
    if ($_ -match '^[^#][^=]+=(.*)$') {
        $name, $value = $_ -split '=', 2
        Set-Item -Path "Env:$name" -Value $value
    }
}

$env:DATAHUB_VERSION = 'v1.6.0'
$env:UI_INGESTION_DEFAULT_CLI_VERSION = '1.6.0.15'

& docker compose -f $quickstartCompose -p datahub --profile quickstart up -d --wait
if ($LASTEXITCODE -ne 0) {
    throw 'DataHub containers did not become healthy.'
}

if (-not $SkipDatapack) {
    & .\scripts\load-showcase-data.ps1
    if ($LASTEXITCODE -ne 0) {
        throw 'The showcase-ecommerce metadata load failed.'
    }
}

Write-Output 'DataHub is available at http://localhost:9002 (local account: datahub / datahub).'
