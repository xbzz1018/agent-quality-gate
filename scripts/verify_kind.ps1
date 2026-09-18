[CmdletBinding()]
param(
    [string]$KindPath = "",
    [string]$ClusterName = "aqh-closeout",
    [int]$WaitSeconds = 420
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($KindPath)) {
    $KindPath = Join-Path $projectRoot ".tmp\kind.exe"
}
if (-not (Test-Path -LiteralPath $KindPath -PathType Leaf)) {
    throw "kind is unavailable at $KindPath"
}

$clusters = & $KindPath get clusters
if ($clusters -notcontains $ClusterName) {
    & $KindPath create cluster --name $ClusterName `
        --config (Join-Path $projectRoot "deploy\k8s\kind-config.yaml")
    if ($LASTEXITCODE -ne 0) { throw "kind cluster creation failed" }
}

docker tag agent-quality-gate-api:latest agent-quality-gate-api:local
docker tag agent-quality-gate-web:latest agent-quality-gate-web:local
docker tag agent-quality-gate-opa:latest agent-quality-gate-opa:local
& $KindPath load docker-image --name $ClusterName `
    agent-quality-gate-api:local agent-quality-gate-web:local agent-quality-gate-opa:local `
    postgres:17 redis:8-alpine bitnamilegacy/kafka:latest
if ($LASTEXITCODE -ne 0) { throw "kind image load failed" }

$namespacePath = Join-Path $projectRoot "deploy\k8s\namespace.yaml"
kubectl apply -f $namespacePath | Out-Null
$bytes = New-Object byte[] 48
$random = [Security.Cryptography.RandomNumberGenerator]::Create()
$random.GetBytes($bytes)
$jwtSecret = [Convert]::ToHexString($bytes)
$random.GetBytes($bytes)
$databasePassword = [Convert]::ToHexString($bytes)
$databaseUrl = "postgresql+psycopg://agent_quality:$databasePassword@postgres:5432/agent_quality"
try {
    kubectl -n agent-quality-harness create secret generic aqh-secrets `
        --from-literal="jwt-secret=$jwtSecret" `
        --from-literal="postgres-password=$databasePassword" `
        --from-literal="database-url=$databaseUrl" `
        --dry-run=client -o yaml | kubectl apply -f - | Out-Null
    kubectl apply -k (Join-Path $projectRoot "deploy\k8s") | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Kubernetes apply failed" }

    $deployments = @(
        "postgres", "redis", "kafka", "opa", "api", "kafka-publisher",
        "kafka-worker", "fake-agent", "web"
    )
    foreach ($deployment in $deployments) {
        kubectl -n agent-quality-harness rollout status "deployment/$deployment" `
            "--timeout=${WaitSeconds}s"
        if ($LASTEXITCODE -ne 0) { throw "Deployment failed: $deployment" }
    }
    $apiHpa = kubectl -n agent-quality-harness get hpa api -o json | ConvertFrom-Json
    $workerHpa = kubectl -n agent-quality-harness get hpa kafka-worker -o json | ConvertFrom-Json
    if ($apiHpa.spec.maxReplicas -ne 3 -or $workerHpa.spec.maxReplicas -ne 4) {
        throw "HPA configuration does not match the verified limits"
    }
    $health = Invoke-RestMethod "http://127.0.0.1:18080/api/v1/health/ready" -TimeoutSec 10
    if ($health.status -ne "ready" -or $health.components.kafka -ne "ok") {
        throw "kind API readiness did not verify Kafka"
    }
    $report = [ordered]@{
        cluster = $ClusterName
        namespace = "agent-quality-harness"
        deployments = $deployments
        api_hpa_max = $apiHpa.spec.maxReplicas
        worker_hpa_max = $workerHpa.spec.maxReplicas
        readiness = $health
        web_url = "http://127.0.0.1:18080"
        verified_at = (Get-Date).ToUniversalTime().ToString("o")
    }
    $report | ConvertTo-Json -Depth 8 | Set-Content `
        -LiteralPath (Join-Path $projectRoot ".tmp\kind-verification.json") `
        -Encoding utf8
    $report | ConvertTo-Json -Depth 8
}
finally {
    $jwtSecret = $null
    $databasePassword = $null
    $databaseUrl = $null
    $bytes = $null
    $random.Dispose()
    $random = $null
}
