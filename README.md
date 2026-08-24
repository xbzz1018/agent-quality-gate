# Agent Quality Harness

Agent 的自动化评测、调用链追踪、失败回放和 CI 发布门禁平台。当前状态为 `本地多租户 MVP 已完成`；下列 Pending/Optional 能力仍不得作为已实现功能宣称。

## 当前实施边界

- Complete backend MVP：FastAPI、PostgreSQL/Alembic、可靠 Redis Worker、Inspect AI、HTTP/SSE、确定性 Scorer、Baseline/Candidate、Gate、失败回放、Token/Cost、持久事件与 Gate CLI。
- Verified：运行前 Dataset 哈希复核、同 Target 默认约束、pending Adapter 预检、真实 Trace ID、失败 case 回放、queued 取消、版本对比和 SHIP/WARN/BLOCK 边界。
- Complete multi-tenant management：Organization、全局 User/多组织 Membership、动态 Role/Permission、Argon2id、15 分钟 Access JWT、7 天轮换 Refresh Session、组织级 Service Account/API Key 和脱敏审计。
- Complete Web MVP：Vue 3 + TypeScript + Element Plus + Vite 操作台；登录/组织切换、目标/版本、数据集、运行、Case/Trace 双栏、版本对比、发布门禁、成本、审计和系统管理均使用真实 API。
- Verified hardening：Collector/Jaeger 端到端导出、长批次 lease heartbeat、running 协作取消、Candidate-only `baseline_required`。
- Real targets：AgriGraph 40/40 characterization 完成；Document Autoflow 1/1 Profile 烟测完成，24 条整轮因目标 REPROCESS 长任务保持 Pending。
- Pending：Document Autoflow 24 条完整轮次、AG-UI、Agent Skills/OPA、DeepAgents、A2A、MCP。
- Optional：Kafka、Kubernetes、MCP Tasks、Hermes 兼容。

Redis Worker 在 MVP 中领取整个 EvalRun，case 并发由 Inspect AI 控制。HTTP/SSE/A2A 属于 AgentTargetAdapter，MCP 属于 ToolTargetAdapter。

## 环境

```powershell
conda env create -f environment.yml
conda activate agent-quality-gate
python -m pip check
```

环境包含 FastAPI、Inspect AI、DeepAgents、A2A SDK、MCP SDK、Kafka Python Client 与 OpenTelemetry。PostgreSQL、Redis、Kafka、Jaeger 和 OpenTelemetry Collector 作为 Docker 服务运行，不安装进 Conda。

## 本地运行

```powershell
conda activate agent-quality-gate
python -m pip install -e . --no-deps
docker compose up -d postgres redis
python -m alembic upgrade head
\"请在这里输入至少 12 位强密码\" | aqh admin bootstrap --username admin --display-name \"Platform Administrator\" --password-stdin
python -m uvicorn agent_quality_harness.main:app --host 127.0.0.1 --port 8010
```

另开终端启动 Worker：

```powershell
conda activate agent-quality-gate
python -m agent_quality_harness.worker
```

另开终端启动明确命名的本地 Fake Agent：

```powershell
conda activate agent-quality-gate
python -m uvicorn agent_quality_harness.fake_agent:app --host 127.0.0.1 --port 8020
```

启动 Vue 开发服务器（`/api` 自动代理到端口 8010）：

```powershell
cd web
npm install
npm run dev
```

Web：`http://127.0.0.1:5173`。API 文档：`http://127.0.0.1:8010/docs`。平台不内置默认密码，首次启动必须通过上面的 stdin 命令创建管理员。

推荐用 Compose 启动已验收的完整本地拓扑。JWT 密钥只进入当前 PowerShell 会话，不写入仓库：

```powershell
$bytes = New-Object byte[] 64
[Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
$env:AQH_JWT_SECRET = [Convert]::ToBase64String($bytes)

docker compose up -d --build `
  postgres redis jaeger otel-collector `
  api worker fake-agent web
```

Web 为 `http://127.0.0.1:5173`，API 文档为 `http://127.0.0.1:8000/docs`，Jaeger 为 `http://127.0.0.1:16686`。Nginx 将同源 `/api/v1` 请求代理到 API；生产 Web 不依赖 Vite 开发代理。Collector 健康端点为 `http://127.0.0.1:13133/`。真实 Trace 验证：

```powershell
python scripts/verify_telemetry.py --trace-id <trace-id> --expected-service agent-quality-harness-worker
```

关闭服务但保留管理员和历史运行：

```powershell
docker compose down
Remove-Item Env:AQH_JWT_SECRET
```

不要执行 `docker compose down -v`，该命令会删除 PostgreSQL/Redis 数据卷。生产镜像使用 `requirements-runtime.txt`，只包含 `v0.1.0` 已实现运行时；A2A、MCP、DeepAgents、Kafka 等 pending/optional 依赖不会因为存在于开发环境就被打包成已完成功能。

进入 Web 后点击“初始化 Demo Fixture”会创建明确标记的 Fake Agent Target、Baseline/Candidate、80 条冻结样例、GatePolicy 和 PricingSnapshot。该操作不伪造评测结果，仍需创建运行并由 Worker 实际执行。

## 验证

```powershell
python -m ruff check .
python -m pytest -m "not integration"
$env:AQH_RUN_INTEGRATION = "1"
python -m pytest tests/test_integration_run.py -q
python -m alembic check
cd web
npm run typecheck
npm test
npm run build
```

集成测试只使用项目三的 PostgreSQL/Redis，并按本次测试创建的 ID 清理数据。

Gate CLI：

```powershell
$env:AQH_API_KEY = \"只显示一次的组织级 API Key\"
aqh gate --run-id 123 --api-url http://127.0.0.1:8010
aqh gate --report tests/fixtures/gate-ship.json
```

`SHIP/WARN` 返回 0，`BLOCK/FAILED` 返回非零。`datasets/` 中的 80 条 core 和 20 条 stability 数据均明确标记为 Demo Fixture；两个真实 Profile 均已 live verification，但 Document Autoflow 24 条完整轮次仍为 Pending。

## 真实目标 Characterization

冻结并复核真实目标数据：

```powershell
python scripts/freeze_real_targets.py --check
```

`auth_ref` 只保存环境变量名。变量值支持旧版静态 Header JSON，以及以下登录模式；真实值不得写入 Git：

```json
{"type":"bearer_login","username":"...","password":"..."}
{"type":"cookie_login","username":"...","password":"..."}
```

执行 Candidate-only 运行：

```powershell
$env:AQH_OTEL_ENABLED = "true"
$env:AQH_OTEL_EXPORTER_OTLP_ENDPOINT = "http://127.0.0.1:4317"
python scripts/run_real_characterization.py agrigraph
python scripts/run_real_characterization.py document-autoflow --capabilities .tmp/document-autoflow-capabilities.json
```

没有 Baseline 时，Comparison/Gate 返回 `baseline_required`，不会生成 SHIP/WARN/BLOCK。当前实测记录：AgriGraph Run `#53` 为 40/40 completed、32/40 规则通过、费用 UNKNOWN；Document Autoflow Run `#55` 为 1/1 completed、模型费用 `$0.00158228`。Document 完整 Run `#54` 因目标 REPROCESS 超过 600 秒而失败，仍保留为审计证据。
