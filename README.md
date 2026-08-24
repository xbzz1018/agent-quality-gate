# Agent Quality Harness

Agent 的自动化评测、调用链追踪、失败回放和 CI 发布门禁平台。当前状态为 `本地多租户 MVP 已完成`；下列 Pending/Optional 能力仍不得作为已实现功能宣称。

当前发布候选版本为 `v0.5.0-multi-skill-reliability`。平台与 DeepAgents 被测镜像分别使用 `requirements-runtime.lock` 和 `requirements-deep-agent.lock` 的精确传递依赖；生产安装不解析开发依赖。

`v0.3.0-security-gate` 保留为安全门禁基线；`v0.4.0-ag-ui` 在其后加入 AG-UI 0.1.19、运行中流取消、OPA CI/readiness、密钥导入拒绝和 Policy 绑定 UI。

`v0.5.0-multi-skill-reliability` 增加 `aqh.skill-manifest/v1`、原子绑定冲突检查、跨协议 `aqh.skill-event/v1`、Skill 选择/身份/生命周期 Scorer、冻结数据集 Coverage 和 EvidenceRef 归因门禁。平台仍不执行或路由 Skill。

## 当前实施边界

- Complete backend MVP：FastAPI、PostgreSQL/Alembic、可靠 Redis Worker、Inspect AI、HTTP/SSE、确定性 Scorer、Baseline/Candidate、Gate、失败回放、Token/Cost、持久事件与 Gate CLI。
- Verified：运行前 Dataset 哈希复核、同 Target 默认约束、pending Adapter 预检、真实 Trace ID、失败 case 回放、queued 取消、版本对比和 SHIP/WARN/BLOCK 边界。
- Complete multi-tenant management：Organization、全局 User/多组织 Membership、动态 Role/Permission、Argon2id、15 分钟 Access JWT、7 天轮换 Refresh Session、组织级 Service Account/API Key 和脱敏审计。
- Complete Web MVP：Vue 3 + TypeScript + Element Plus + Vite 操作台；登录/组织切换、目标/版本、数据集、运行、Case/Trace 双栏、版本对比、发布门禁、成本、审计和系统管理均使用真实 API。
- Verified hardening：Collector/Jaeger 端到端导出、长批次 lease heartbeat、running 协作取消、Candidate-only `baseline_required`。
- Real targets：AgriGraph 40/40 characterization 完成；Document Autoflow 1/1 Profile 烟测完成，24 条整轮因目标 REPROCESS 长任务保持 Pending。
- Complete protocol adapters：A2A 1.1 AgentTargetAdapter，以及独立的 MCP 2.0 ToolTargetAdapter（Tool/Resource/Prompt）。
- Complete execution target：DeepAgents 0.7.6 作为独立 HTTP 被测容器，并保留 plain control Baseline；它不进入平台 API/Worker 运行时。
- Complete security gate：组织隔离的 Agent Skills 不可变版本、确定性安全扫描、Baseline/Candidate 安全回归，以及 OPA/Rego Policy-as-Code fail-closed 组合门禁。
- Complete AG-UI branch：标准 RunAgentInput/SSE BaseEvent、文本/Tool/State/Token 映射、活动流关闭取消与隐藏推理丢弃。
- Pending：Document Autoflow 24 条完整轮次。
- Optional：Kafka、Kubernetes、MCP Tasks、Hermes 兼容。

Redis Worker 在 MVP 中领取整个 EvalRun，case 并发由 Inspect AI 控制。HTTP/SSE/A2A 属于 AgentTargetAdapter，MCP 属于 ToolTargetAdapter。

## 环境

```powershell
conda env create -f environment.yml
conda activate agent-quality-gate
python -m pip check
```

环境包含 FastAPI、Inspect AI、DeepAgents、A2A SDK、MCP SDK、Kafka Python Client 与 OpenTelemetry。PostgreSQL、Redis、OPA、Jaeger 和 OpenTelemetry Collector 作为当前 Docker 服务运行；Kafka 仍是 Optional，尚未进入运行拓扑。

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
  postgres redis opa jaeger otel-collector `
  api worker fake-agent fake-mcp fake-ag-ui deep-agent web
```

Web 为 `http://127.0.0.1:5173`，API 文档为 `http://127.0.0.1:8000/docs`，OPA 为 `http://127.0.0.1:8181`，Jaeger 为 `http://127.0.0.1:16686`。Nginx 将同源 `/api/v1` 请求代理到 API；生产 Web 不依赖 Vite 开发代理。Collector 健康端点为 `http://127.0.0.1:13133/`。真实 Trace 验证：

```powershell
python scripts/verify_telemetry.py --trace-id <trace-id> --expected-service agent-quality-harness-worker
```

关闭服务但保留管理员和历史运行：

```powershell
docker compose down
Remove-Item Env:AQH_JWT_SECRET
```

不要执行 `docker compose down -v`，该命令会删除 PostgreSQL/Redis 数据卷。平台镜像使用 `requirements-runtime.txt`，包含已验收的 Inspect、A2A 与 MCP；DeepAgents 只存在于 `Dockerfile.deep-agent` 构建的被测容器中，Kafka 等 optional 依赖不会因为存在于开发环境就被打包成已完成功能。

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

集成测试只使用项目三的 PostgreSQL、Redis 和 OPA，并按本次测试创建的组织与队列清理数据。

## Skills 与 Policy-as-Code

`POST /api/v1/skills/import` 只接收结构化 UTF-8 文件列表，最多 100 个文件、合计 1 MiB；绝对路径、路径穿越、重复路径和二进制内容会被拒绝。扫描器 `skills-static-v1` 的确定性 BLOCK/WARN 发现会持久化，AgentVersion 一旦被 EvalRun 引用便不能改变 Skill 绑定。

Rego Bundle 必须使用 `aqh.org_<organization_id>.<policy>.v_<version>` 命名空间。只有经 OPA 编译为 `validated` 的不可变 Bundle 才能绑定 GatePolicy；显式绑定后，OPA 超时、不可用、undefined 或非法输出统一 fail-closed 为 `BLOCK / policy_engine_error`。最终 Gate 取内置指标规则、Skill 回归和 OPA 决策中最严格者。

Gate CLI：

```powershell
$env:AQH_API_KEY = \"只显示一次的组织级 API Key\"
aqh gate --run-id 123 --api-url http://127.0.0.1:8010
aqh gate --report tests/fixtures/gate-ship.json
```

`SHIP/WARN` 返回 0，`BLOCK/FAILED` 返回非零。`datasets/` 中的 80 条 core 和 20 条 stability 数据均明确标记为 Demo Fixture；两个真实 Profile 均已 live verification，但 Document Autoflow 24 条完整轮次仍为 Pending。

## 协议目标

- AG-UI Target 使用标准 HTTP POST `RunAgentInput` 与 SSE `BaseEvent`，当前锁定 `ag-ui-protocol==0.1.19`。Adapter 要求 RUN_STARTED 和 RUN_FINISHED/RUN_ERROR 完整生命周期，使用 RFC 6902 应用 State Delta，合并 Tool Call 参数分片，并丢弃 reasoning content 与 encrypted value。Fake Target 为 `http://127.0.0.1:8050/ag-ui`。
- A2A Target 的 endpoint 是 Agent Card 基址，例如 `http://fake-agent:8020/a2a`；Adapter 使用官方 SDK 完成 Card 版本发现、消息/Task、状态轮询和取消。A2A 没有统一用量字段时 Token/费用保持 UNKNOWN/null。
- MCP Target 必须使用 `target_kind=tool`，endpoint 支持 Streamable HTTP 或受控 `stdio://` 配置。数据集 case 通过 `operation` 选择 `call_tool`、`read_resource`、`get_prompt` 及对应 list 操作；MCP Tasks 仍明确为实验 pending。
- DeepAgents Fixture 位于 `http://127.0.0.1:8040`。同一 HTTP Target 使用 `control` Baseline 和 `deepagents` Candidate，便于比较执行框架开销，而不是把 DeepAgents 变成平台依赖。

已验证运行：A2A Run `#74` 为 2/2 通过且 `baseline_required`；MCP Run `#75` 为 Tool/Resource/Prompt 3/3 通过且 `baseline_required`；DeepAgents Run `#76` 为 4/4 结果通过，Candidate P95 33 ms 对 Baseline 17 ms，按策略产生真实 `WARN`。

AG-UI Compose Fixture 可重复执行：

```powershell
python scripts/run_ag_ui_fixture.py
```

当前验证 Run `#96` 为 3/3 规则通过，包含 1 条真实 UNKNOWN 用量记录；Worker Trace `7a233a7fe8b7c339f9dc3a2b0c8e2eb3` 在 Jaeger 中包含 10 spans、敏感 tag 0。Agent 事件中的 reasoning 只保留空载荷开始/结束元数据。

多 Skill 可重复验收：

```powershell
python scripts/run_multi_skill_fixture.py
```

Run `#119` 的 Baseline/Candidate 共 4/4 结果通过，Skill selection、Evidence 和 Coverage 均为 1.0，发布门禁为 `SHIP`。平台只验证冻结 Claim→EvidenceRef 映射和引用完整性，不宣称识别所有开放域事实幻觉。

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
