[CmdletBinding()]
param(
    [ValidateSet("redis", "kafka")]
    [string]$QueueBackend = "redis",
    [switch]$Observability,
    [switch]$Build
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$cipherPath = Join-Path $projectRoot ".tmp\document-autoflow-auth.dpapi"
$secure = if (Test-Path -LiteralPath $cipherPath -PathType Leaf) {
    ConvertTo-SecureString ((Get-Content -LiteralPath $cipherPath -Raw).Trim())
} else { $null }
$agriCipherPath = Join-Path $projectRoot ".tmp\agrigraph-auth.dpapi"
$agriSecure = if (Test-Path -LiteralPath $agriCipherPath -PathType Leaf) {
    ConvertTo-SecureString ((Get-Content -LiteralPath $agriCipherPath -Raw).Trim())
} else { $null }
$pointer = [IntPtr]::Zero
$agriPointer = [IntPtr]::Zero
$jwtBytes = New-Object byte[] 64
$random = [Security.Cryptography.RandomNumberGenerator]::Create()
try {
    if ($null -ne $secure) {
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        $env:AQH_DOCUMENT_AUTOFLOW_AUTH = `
            [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    if ($null -ne $agriSecure) {
        $agriPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($agriSecure)
        $env:AQH_AGRIGRAPH_AUTH = `
            [Runtime.InteropServices.Marshal]::PtrToStringBSTR($agriPointer)
    }
    $random.GetBytes($jwtBytes)
    $env:AQH_JWT_SECRET = [Convert]::ToBase64String($jwtBytes)
    $env:AQH_QUEUE_BACKEND = $QueueBackend
    if ($Observability) { $env:AQH_OTEL_ENABLED = "true" }
    Push-Location $projectRoot
    try {
        $buildArgs = if ($Build) { @("--build") } else { @() }
        if ($QueueBackend -eq "kafka") {
            docker compose stop worker
            docker compose --profile distributed up -d @buildArgs `
                postgres redis kafka opa api kafka-publisher kafka-worker fake-agent web
        }
        else {
            docker compose up -d @buildArgs `
                postgres redis opa api worker fake-agent web
        }
        if ($Observability) {
            docker compose --profile observability up -d jaeger otel-collector
        }
        if ($LASTEXITCODE -ne 0) { throw "Agent Quality Harness Compose startup failed" }
    }
    finally {
        Pop-Location
    }
}
finally {
    if ($pointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    if ($agriPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($agriPointer)
    }
    Remove-Item Env:AQH_AGRIGRAPH_AUTH -ErrorAction SilentlyContinue
    Remove-Item Env:AQH_DOCUMENT_AUTOFLOW_AUTH -ErrorAction SilentlyContinue
    Remove-Item Env:AQH_JWT_SECRET -ErrorAction SilentlyContinue
    Remove-Item Env:AQH_QUEUE_BACKEND -ErrorAction SilentlyContinue
    Remove-Item Env:AQH_OTEL_ENABLED -ErrorAction SilentlyContinue
    $jwtBytes = $null
    $random.Dispose()
    $random = $null
}
