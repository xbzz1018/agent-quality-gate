[CmdletBinding()]
param(
    [string]$AgriGraphRoot = "F:\code\homework\project\2-AgriGraph"
)

$ErrorActionPreference = "Stop"
$harnessRoot = Split-Path -Parent $PSScriptRoot
$agriRoot = (Resolve-Path -LiteralPath $AgriGraphRoot).Path
$infraEnv = Join-Path $agriRoot "var\acceptance\infra.env"
if (-not (Test-Path -LiteralPath $infraEnv -PathType Leaf)) {
    throw "AgriGraph acceptance environment is unavailable"
}
$condaExe = "D:\Codesoftwares\anaconda\Anaconda3\Scripts\conda.exe"
if (-not (Test-Path -LiteralPath $condaExe -PathType Leaf)) {
    throw "Conda executable is unavailable"
}

$passwordBytes = New-Object byte[] 32
$random = [Security.Cryptography.RandomNumberGenerator]::Create()
$random.GetBytes($passwordBytes)
$evaluatorPassword = [Convert]::ToBase64String($passwordBytes)
$runtime = Join-Path $agriRoot "var\aqh-closeout"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

try {
    Push-Location $agriRoot
    try {
        docker compose --project-name agrigraph-acceptance --env-file $infraEnv `
            -f compose.acceptance.yml up -d --wait elasticsearch neo4j minio
        if ($LASTEXITCODE -ne 0) { throw "AgriGraph dependencies failed to start" }

        $env:AGRIGRAPH_RESET_USERNAME = "aqh_evaluator"
        $env:AGRIGRAPH_RESET_PASSWORD = $evaluatorPassword
        Push-Location (Join-Path $agriRoot "backend-python")
        try {
            & $condaExe run -n AiJava --no-capture-output python `
                -m app.cli.reset_password --create --role USER
        }
        finally {
            Pop-Location
        }
        if ($LASTEXITCODE -ne 0) { throw "AgriGraph evaluator bootstrap failed" }

        if (-not (Get-NetTCPConnection -State Listen -LocalPort 8088 -ErrorAction SilentlyContinue)) {
            $env:AGRIGRAPH_CONDA_EXE = $condaExe
            Start-Process powershell `
                -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", `
                    (Join-Path $agriRoot "scripts\dev\run-python-backend-aijava.ps1"), `
                    "-Port", "8088", "-EnvFilePath", $infraEnv `
                -WindowStyle Hidden `
                -RedirectStandardOutput (Join-Path $runtime "api.out.log") `
                -RedirectStandardError (Join-Path $runtime "api.err.log") | Out-Null
        }
        $deadline = (Get-Date).AddMinutes(3)
        $ready = $false
        do {
            try {
                Invoke-RestMethod "http://127.0.0.1:8088/api/v1/health" -TimeoutSec 3 |
                    Out-Null
                $ready = $true
            }
            catch {
                Start-Sleep -Seconds 2
            }
        } while (-not $ready -and (Get-Date) -lt $deadline)
        if (-not $ready) { throw "AgriGraph API did not become healthy" }

        $authPayload = @{
            type = "bearer_login"
            username = "aqh_evaluator"
            password = $evaluatorPassword
        } | ConvertTo-Json -Compress
        $login = Invoke-RestMethod "http://127.0.0.1:8088/api/v1/users/login" `
            -Method Post -ContentType "application/json" `
            -Body (@{ username = "aqh_evaluator"; password = $evaluatorPassword } |
                ConvertTo-Json -Compress)
        if ([string]::IsNullOrWhiteSpace([string]$login.data.token)) {
            throw "AgriGraph evaluator login did not return a token"
        }
        $secure = ConvertTo-SecureString $authPayload -AsPlainText -Force
        ConvertFrom-SecureString $secure | Set-Content `
            -LiteralPath (Join-Path $harnessRoot ".tmp\agrigraph-auth.dpapi") `
            -Encoding utf8
        Write-Output "AgriGraph closeout target is ready"
    }
    finally {
        Pop-Location
    }
}
finally {
    Remove-Item Env:AGRIGRAPH_RESET_USERNAME -ErrorAction SilentlyContinue
    Remove-Item Env:AGRIGRAPH_RESET_PASSWORD -ErrorAction SilentlyContinue
    Remove-Item Env:AGRIGRAPH_CONDA_EXE -ErrorAction SilentlyContinue
    $evaluatorPassword = $null
    $passwordBytes = $null
    $random.Dispose()
    $random = $null
}
