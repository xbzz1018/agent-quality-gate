[CmdletBinding()]
param(
    [string]$DocumentRoot = "F:\code\homework\project\document-autoflow",
    [string]$ProjectId = "f3d26828-dee0-4b22-b2c7-040cf6bea0d5",
    [string]$TemplateId = "d93c452f-e201-4835-952c-cf949470fe88",
    [string]$RepairDocumentId = "ee0c16ff-8949-4d63-a32f-1928c0025562"
)

$ErrorActionPreference = "Stop"
$harnessRoot = Split-Path -Parent $PSScriptRoot
$documentRootPath = (Resolve-Path -LiteralPath $DocumentRoot).Path
$secretFunctions = Join-Path $documentRootPath "scripts\local_secrets.ps1"
. $secretFunctions

$databasePassword = Get-LocalSecretText -Name "database_password"
if ([string]::IsNullOrWhiteSpace($databasePassword)) {
    throw "Document Autoflow database secret is unavailable"
}
$passwordBytes = New-Object byte[] 32
$random = [Security.Cryptography.RandomNumberGenerator]::Create()
$random.GetBytes($passwordBytes)
$random.Dispose()
$evaluatorPassword = [Convert]::ToBase64String($passwordBytes)
$runtime = Join-Path $documentRootPath "runtime\aqh-closeout"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

try {
    $env:DOCUMENT_AUTOFLOW_DATABASE_PASSWORD = $databasePassword
    $env:DOCUMENT_AUTOFLOW_DATABASE_USER = "precheck"
    $env:DOCUMENT_AUTOFLOW_DATABASE_NAME = "document_autoflow"
    $env:DOCUMENT_AUTOFLOW_DATABASE_HOST = "127.0.0.1"
    $env:DOCUMENT_AUTOFLOW_DATABASE_PORT = "56432"
    $env:DOCUMENT_AUTOFLOW_AQH_PASSWORD = $evaluatorPassword
    $env:DOCUMENT_AUTOFLOW_TEMPORAL_MODE = "server"
    $env:DOCUMENT_AUTOFLOW_TEMPORAL_TARGET_HOST = "127.0.0.1:7233"
    $env:DOCUMENT_AUTOFLOW_MAX_DOCUMENTS_PER_PROJECT = "30"

    & (Join-Path $documentRootPath "scripts\start_postgres.ps1")
    & "D:\Codesoftwares\anaconda\Anaconda3\envs\openai\python.exe" `
        (Join-Path $PSScriptRoot "bootstrap_document_autoflow_evaluator.py") `
        --document-root $documentRootPath

    if (-not (Get-NetTCPConnection -State Listen -LocalPort 7233 -ErrorAction SilentlyContinue)) {
        Start-Process powershell `
            -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", `
                (Join-Path $documentRootPath "scripts\start_temporal_dev_server.ps1") `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $runtime "temporal.out.log") `
            -RedirectStandardError (Join-Path $runtime "temporal.err.log") | Out-Null
    }
    $deadline = (Get-Date).AddMinutes(2)
    while (-not (Get-NetTCPConnection -State Listen -LocalPort 7233 -ErrorAction SilentlyContinue)) {
        if ((Get-Date) -gt $deadline) { throw "Temporal did not start" }
        Start-Sleep -Seconds 2
    }

    if (-not (Get-NetTCPConnection -State Listen -LocalPort 8030 -ErrorAction SilentlyContinue)) {
        Start-Process powershell `
            -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", `
                (Join-Path $documentRootPath "scripts\start_app.ps1"), "-Port", "8030" `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $runtime "api.out.log") `
            -RedirectStandardError (Join-Path $runtime "api.err.log") | Out-Null
    }
    Start-Process powershell `
        -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", `
            (Join-Path $documentRootPath "scripts\start_document_worker.ps1") `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $runtime "worker.out.log") `
        -RedirectStandardError (Join-Path $runtime "worker.err.log") | Out-Null

    $deadline = (Get-Date).AddMinutes(3)
    $ready = $false
    do {
        try {
            Invoke-RestMethod "http://127.0.0.1:8030/health" -TimeoutSec 3 | Out-Null
            $ready = $true
        }
        catch {
            Start-Sleep -Seconds 2
        }
    } while (-not $ready -and (Get-Date) -lt $deadline)
    if (-not $ready) { throw "Document Autoflow API did not become healthy" }

    $session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
    $loginBody = @{ username = "aqh_evaluator"; password = $evaluatorPassword } |
        ConvertTo-Json -Compress
    Invoke-RestMethod "http://127.0.0.1:8030/api/v1/auth/login" `
        -Method Post -ContentType "application/json" -Body $loginBody -WebSession $session |
        Out-Null
    $documentUrl = "http://127.0.0.1:8030/api/v1/documents/$RepairDocumentId"
    $document = Invoke-RestMethod $documentUrl -WebSession $session
    if ($document.status -ne "parsed") {
        Invoke-RestMethod "$documentUrl/reparse" -Method Post -ContentType "application/json" `
            -Body '{"parse_mode":"auto"}' -WebSession $session | Out-Null
        $deadline = (Get-Date).AddMinutes(15)
        do {
            Start-Sleep -Seconds 2
            $document = Invoke-RestMethod $documentUrl -WebSession $session
        } while ($document.status -in @("queued", "processing") -and (Get-Date) -lt $deadline)
    }
    if ($document.status -ne "parsed") {
        throw "Document reparse ended as $($document.status)"
    }

    $authPayload = @{
        type = "cookie_login"
        username = "aqh_evaluator"
        password = $evaluatorPassword
    } | ConvertTo-Json -Compress
    $env:AQH_DOCUMENT_AUTOFLOW_AUTH = $authPayload
    & "D:\Codesoftwares\anaconda\Anaconda3\envs\agent-quality-gate\python.exe" `
        (Join-Path $PSScriptRoot "prepare_document_autoflow_target.py") `
        --base-url "http://127.0.0.1:8030" `
        --reuse-project-id $ProjectId `
        --reuse-template-id $TemplateId

    $secure = ConvertTo-SecureString $authPayload -AsPlainText -Force
    ConvertFrom-SecureString $secure | Set-Content `
        -LiteralPath (Join-Path $harnessRoot ".tmp\document-autoflow-auth.dpapi") `
        -Encoding utf8
    Write-Output "Document Autoflow closeout target is ready with 24 parsed documents"
}
finally {
    Get-ChildItem Env:DOCUMENT_AUTOFLOW_* -ErrorAction SilentlyContinue | Remove-Item
    Remove-Item Env:AQH_DOCUMENT_AUTOFLOW_AUTH -ErrorAction SilentlyContinue
    $databasePassword = $null
    $evaluatorPassword = $null
    $passwordBytes = $null
    $random = $null
}
