[CmdletBinding()]
param(
    [string]$AgriGraphRoot = "F:\code\homework\project\2-AgriGraph",
    [string]$KeyDpapiPath = "",
    [int]$ApiPort = 8088
)

$ErrorActionPreference = "Stop"
$harnessRoot = Split-Path -Parent $PSScriptRoot
$agriRoot = (Resolve-Path -LiteralPath $AgriGraphRoot).Path
$backendRoot = Join-Path $agriRoot "backend-python"
$infraEnv = Join-Path $agriRoot "var\acceptance\infra.env"
$condaExe = "D:\Codesoftwares\anaconda\Anaconda3\Scripts\conda.exe"
$model = "qwen3.7-text-embedding"
$dimensions = 1024

if ((Get-PSDrive E).Free -lt 20GB) {
    throw "E drive has less than 20 GB free; Embedding migration is blocked"
}
if (-not (Test-Path -LiteralPath $infraEnv -PathType Leaf)) {
    throw "AgriGraph acceptance environment is unavailable"
}
if (-not $KeyDpapiPath) {
    $KeyDpapiPath = Join-Path $harnessRoot ".tmp\agrigraph-embedding.dpapi"
}

function Import-DotEnv([string]$Path) {
    Get-Content -LiteralPath $Path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        $parts = $line -split "=", 2
        if ($parts.Count -eq 2) {
            Set-Item -Path "Env:$($parts[0].Trim())" -Value $parts[1].Trim().Trim('"').Trim("'")
        }
    }
}

function Convert-LastJson([object[]]$Lines) {
    $line = @($Lines | Where-Object { -not [string]::IsNullOrWhiteSpace([string]$_) })[-1]
    if (-not $line) { throw "Command did not return a JSON result" }
    return $line | ConvertFrom-Json
}

$embeddingKey = $env:AGRIGRAPH_NEW_EMBEDDING_API_KEY
$embeddingBase = $env:AGRIGRAPH_NEW_EMBEDDING_API_BASE
if ([string]::IsNullOrWhiteSpace($embeddingKey) -and (Test-Path -LiteralPath $KeyDpapiPath)) {
    $encrypted = (Get-Content -LiteralPath $KeyDpapiPath -Raw).Trim()
    $secure = ConvertTo-SecureString $encrypted
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $embeddingKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}
if ([string]::IsNullOrWhiteSpace($embeddingKey) -or [string]::IsNullOrWhiteSpace($embeddingBase)) {
    throw "Set rotated AGRIGRAPH_NEW_EMBEDDING_API_KEY and AGRIGRAPH_NEW_EMBEDDING_API_BASE locally"
}

try {
    Import-DotEnv $infraEnv
    $env:EMBEDDING_API_KEY = $embeddingKey
    $env:EMBEDDING_API_BASE = $embeddingBase
    $env:EMBEDDING_MODEL = $model
    $env:EMBEDDING_DIMENSIONS = [string]$dimensions
    $env:AGRIGRAPH_ES_VECTOR_MODEL = $model

    $preflight = & $condaExe run -n agent-quality-gate python `
        (Join-Path $PSScriptRoot "verify_agrigraph_embedding.py")
    if ($LASTEXITCODE -ne 0) { throw "Embedding API preflight failed" }
    $preflightJson = Convert-LastJson $preflight
    if ($preflightJson.status -ne "ok" -or $preflightJson.dimensions -ne $dimensions) {
        throw "Embedding API preflight returned an incompatible vector"
    }

    $listener = Get-NetTCPConnection -State Listen -LocalPort $ApiPort -ErrorAction SilentlyContinue
    if ($listener) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
        if (-not $process.CommandLine.Contains($agriRoot)) {
            throw "Port $ApiPort is owned by a process outside AgriGraph; refusing to stop it"
        }
        Stop-Process -Id $listener.OwningProcess
    }

    Push-Location $backendRoot
    try {
        $dryRun = & $condaExe run -n AiJava python -m app.embed_index --dry-run --batch-size 10
        if ($LASTEXITCODE -ne 0) { throw "AgriGraph embed_index dry-run failed" }
        $dryRunJson = Convert-LastJson $dryRun
        if (-not $dryRunJson.documents -or $dryRunJson.dimensions -ne $dimensions) {
            throw "AgriGraph embed_index dry-run found no compatible documents"
        }

        $rebuild = & $condaExe run -n AiJava python -m app.embed_index --batch-size 10
        if ($LASTEXITCODE -ne 0) { throw "AgriGraph vector rebuild failed; keep the API stopped" }
        $rebuildJson = Convert-LastJson $rebuild
        if (
            $rebuildJson.documents -ne $rebuildJson.updated -or
            $rebuildJson.embeddingModel -ne $model -or
            $rebuildJson.dimensions -ne $dimensions
        ) {
            throw "Vector rebuild was incomplete; keep the API stopped or use BM25-only degradation"
        }
    }
    finally { Pop-Location }

    [pscustomobject]@{
        Status = "ready"
        Model = $model
        Dimensions = $dimensions
        Discovered = $rebuildJson.documents
        Updated = $rebuildJson.updated
    }
}
finally {
    @(
        "EMBEDDING_API_KEY",
        "EMBEDDING_API_BASE",
        "EMBEDDING_MODEL",
        "EMBEDDING_DIMENSIONS",
        "AGRIGRAPH_ES_VECTOR_MODEL"
    ) | ForEach-Object { Remove-Item "Env:$_" -ErrorAction SilentlyContinue }
    $embeddingKey = $null
    $pointer = $null
    $secure = $null
}
