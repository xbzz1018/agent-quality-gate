# Agent Quality Harness

多智能体评测、受控场景运行、调用链追踪、失败回放和发布门禁控制面。当前状态为 `存储受控的本地多租户控制面已恢复并可运行`。Inspect AI 负责 Dataset、Case 并发、Solver 和 Scorer；Scenario Executor 只负责单个 Case 内的受限多 Agent DAG。默认 Docker 拓扑只启动核心服务，协议、观测、Kafka 和 Kubernetes 必须显式启用。

## 项目定位

这是 Agent 的质量治理平台，不是另一个聊天 Agent。它把一个被测 Agent 注册成有版本的 Target，使用冻结数据集运行 Baseline/Candidate，对输出、工具调用、证据、Trace、Token、成本和安全违规进行评分，最后给出 `SHIP`、`WARN` 或 `BLOCK`。

平台与被测系统分离：Inspect AI 负责评测执行，OpenTelemetry/Jaeger 负责调用链，Gate Engine 负责发布决策；DeepAgents、A2A、AG-UI 和 MCP 只是可选的被测协议或目标适配器，不会偷偷变成平台核心依赖。

现有版本化基线为 `v0.5.0-multi-skill-reliability`；当前工作树在其上增加 Scenario/Kafka/真实复验收口，但按要求没有执行分支、提交、标签或 GitHub 操作。平台与 DeepAgents 被测镜像分别使用 `requirements-runtime.lock` 和 `requirements-deep-agent.lock` 的精确传递依赖；生产安装不解析开发依赖。

`v0.3.0-security-gate` 保留为安全门禁基线；`v0.4.0-ag-ui` 在其后加入 AG-UI 0.1.19、运行中流取消、OPA CI/readiness、密钥导入拒绝和 Policy 绑定 UI。

`v0.5.0-multi-skill-reliability` 增加 `aqh.skill-manifest/v1`、原子绑定冲突检查、跨协议 `aqh.skill-event/v1`、Skill 选择/身份/生命周期 Scorer、冻结数据集 Coverage 和 EvidenceRef 归因门禁。平台仍不执行或路由 Skill。

## 当前实施边界

- Complete backend MVP：FastAPI、PostgreSQL/Alembic、可靠 Redis Worker、Inspect AI、HTTP/SSE、确定性 Scorer、Baseline/Candidate、Gate、失败回放、Token/Cost、持久事件与 Gate CLI。
- Verified：运行前 Dataset 哈希复核、同 Target 默认约束、pending Adapter 预检、真实 Trace ID、失败 case 回放、queued 取消、版本对比和 SHIP/WARN/BLOCK 边界。
- Complete multi-tenant management：Organization、全局 User/多组织 Membership、动态 Role/Permission、Argon2id、15 分钟 Access JWT、7 天轮换 Refresh Session、组织级 Service Account/API Key 和脱敏审计。
- Complete Web MVP：Vue 3 + TypeScript + Element Plus + Vite 操作台；登录/组织切换、目标/版本、数据集、运行、Case/Trace 双栏、版本对比、发布门禁、成本、审计和系统管理均使用真实 API。
- Verified hardening：Collector/Jaeger 端到端导出、长批次 lease heartbeat、running 协作取消、Candidate-only `baseline_required`。
- Historical real targets：旧数据盘曾完成 AgriGraph 40 条和 Document Autoflow 24 条有界 characterization；对应 Run ID 只作为历史技术记录，不能代表当前数据库。
- Complete protocol adapters：A2A 1.1 AgentTargetAdapter，以及独立的 MCP 2.0 ToolTargetAdapter（Tool/Resource/Prompt）。
- Complete execution target：DeepAgents 0.7.6 作为独立 HTTP 被测容器，并保留 plain control Baseline；它不进入平台 API/Worker 运行时。
- Complete security gate：组织隔离的 Agent Skills 不可变版本、确定性安全扫描、Baseline/Candidate 安全回归，以及 OPA/Rego Policy-as-Code fail-closed 组合门禁。
- Complete AG-UI branch：标准 RunAgentInput/SSE BaseEvent、文本/Tool/State/Token 映射、活动流关闭取消与隐藏推理丢弃。
- Enhanced：MCP Tasks 2025-11-25 实验生命周期、Hermes-compatible Target、Kafka Outbox/Inbox/DLQ 已实现并有测试；不进入默认 Compose。
- Complete scenario control plane：冻结 `aqh.scenario/v1`、最多 4 节点并发、JSON Pointer 交接、Shadow/Pilot、持久节点状态、取消、幂等和 fail-closed Pilot 授权。
- Current-environment verification：Redis Good Run `#10` 为 `SHIP`、Fault Run `#11` 为 `BLOCK`；Kafka Run `#14` 为 `SHIP`；Pilot Scenario Run `#7` 完成；Jaeger Trace `44a6a9d5a6c614f3ab5fac821c0c877f` 包含 Run/Case/Scenario/Agent/Tool 层级且敏感匹配为 0。Document Run `#30` 有 24/24 Characterization 结果，Stability Run `#31` 有 48/48 结果并真实 `BLOCK`；AgriGraph Run `#33` 有 40/40 Characterization 结果，Stability Run `#34` 有 80/80 结果并 `SHIP`。
- Pending：Kubernetes manifests 已生成，但旧 kind 验收被 Docker 数据盘故障中断，当前不宣称本机集群验收完成。

Redis Worker 在 MVP 中领取整个 EvalRun，case 并发由 Inspect AI 控制。HTTP/SSE/A2A 属于 AgentTargetAdapter，MCP 属于 ToolTargetAdapter。

## 环境

```powershell
conda env create -f environment.yml
conda activate agent-quality-gate
python -m pip check
```

环境包含 FastAPI、Inspect AI、DeepAgents、A2A SDK、MCP SDK、Kafka Python Client 与 OpenTelemetry。默认 Docker 只运行 PostgreSQL、Redis、OPA、API、Worker、HTTP Fake Agent 和 Web；其他能力使用 profile，不能静默加入默认拓扑。

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

开发 Web：`http://127.0.0.1:5173`。API 文档：`http://127.0.0.1:8010/docs`。平台不内置默认密码，首次启动必须通过上面的 stdin 命令创建管理员。

推荐用存储受控的 Compose 核心拓扑。已构建镜像时不会再次构建或拉取：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_closeout_stack.ps1
```

当前端口：Web `http://127.0.0.1:5174`，API 文档 `http://127.0.0.1:8000/docs`，OPA `http://127.0.0.1:8181`，Redis host port `56379`。Nginx 将同源 `/api/v1` 代理到 API。首次创建管理员：

```powershell
"至少 12 位强密码" | docker compose exec -T api aqh admin bootstrap `
  --username admin --display-name "Platform Administrator" --password-stdin
```

可选能力必须分开启用，启用前后都运行 `docker system df` 并检查 E 盘余量：

```powershell
docker compose --profile protocols config --services
docker compose --profile observability config --services
docker compose --profile distributed config --services
```

观测栈只在明确需要 Trace 时启动：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_closeout_stack.ps1 -Observability
python scripts/verify_telemetry.py --trace-id <trace-id> --expected-service agent-quality-harness-worker
```

不要同时启用 `protocols + observability + distributed + kind`。E 盘低于 20 GB 时停止构建；不得执行 Volume prune 或 Factory Reset。资源数字是单次检查结果，不是容量承诺，运行前后应重新执行 `docker system df` 和 `Get-PSDrive E`。

关闭服务但保留管理员和历史运行：

```powershell
docker compose down
Remove-Item Env:AQH_JWT_SECRET
```

不要执行 `docker compose down -v`、`docker system prune --volumes` 或 Docker Desktop Factory Reset；它们会删除管理员、历史运行和卷。API 使用轻量 `requirements-api.lock`，HTTP Fake Agent 使用轻量 `requirements-fake-http.lock`，只有 Worker 使用完整 `requirements-runtime.lock`。DeepAgents 和协议 Fixtures 只在显式 profile 中构建。

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

`SHIP/WARN` 返回 0，`BLOCK/FAILED` 返回非零。`datasets/` 中的 80 条 core 和 20 条 stability 数据均明确标记为 Demo Fixture。真实目标验证必须同时检查 Run 状态、结果数量和每条 `failure_type`；`completed` 不能单独证明目标调用成功。

## 适合展示的工程能力

- 冻结数据集、Prompt/Schema/依赖哈希和运行 provenance。
- 确定性 Scorer 优先，LLM-as-Judge 只能补充主观质量，不能覆盖安全和证据门禁。
- Trace、失败 Case 回放、Outbox/Inbox 幂等、Worker lease/heartbeat 和协作式取消。
- 多租户 RBAC、API Key 引用、脱敏审计和 OPA fail-closed 策略。

Kubernetes、Kafka、MCP Tasks、Hermes 和公网高可用仍属于增强项或未验证边界；README 只把当前有测试证据的能力写成完成状态。

## 多智能体 Scenario

`scenario` Target 只能引用同组织冻结的 Agent/Tool Version，不允许嵌套 Scenario、任意代码或运行时提示词规划。`shadow` 拒绝有副作用 Tool；`pilot` 还要求相同 SHA 的最新 Gate 为 `SHIP`、OPA 显式允许、幂等键、并发/超时/Token/费用预算均通过。预算策略要求费用时，UNKNOWN 会 fail closed。

确定性联通场景由 AG-UI Researcher、MCP Tasks Evidence Tool、A2A Reviewer 和 DeepAgents HTTP Coordinator 组成。Redis 是默认队列；Kafka 使用 PostgreSQL Outbox、Consumer、Inbox 幂等和 DLQ，仅在 `distributed` profile 中安装和运行。平台只声明受控本地 Pilot，不承接公网 HA 或通用生产业务编排。

## 协议目标

- AG-UI Target 使用标准 HTTP POST `RunAgentInput` 与 SSE `BaseEvent`，当前锁定 `ag-ui-protocol==0.1.19`。Adapter 要求 RUN_STARTED 和 RUN_FINISHED/RUN_ERROR 完整生命周期，使用 RFC 6902 应用 State Delta，合并 Tool Call 参数分片，并丢弃 reasoning content 与 encrypted value。Fake Target 为 `http://127.0.0.1:8050/ag-ui`。
- A2A Target 的 endpoint 是 Agent Card 基址，例如 `http://fake-agent:8020/a2a`；Adapter 使用官方 SDK 完成 Card 版本发现、消息/Task、状态轮询和取消。A2A 没有统一用量字段时 Token/费用保持 UNKNOWN/null。
- MCP Target 必须使用 `target_kind=tool`，endpoint 支持 Streamable HTTP 或受控 `stdio://` 配置。MCP Tasks 实现 SDK 2.0 可验证的 2025-11-25 实验契约，输出固定标记 `mcp-core-2025-11-25-experimental`；未协商 Tasks capability 时 fail closed。
- Hermes 使用 `hermes_v1` HTTP Target Profile，消费 OpenAI-compatible Chat Completions，不保存 reasoning content；它仍是可选被测对象，不是平台核心依赖。
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

AgriGraph 更换 Embedding 模型时必须先完成原子索引迁移。轮换后的 Key 只放在本机进程环境或当前用户 DPAPI 中：

```powershell
$env:AGRIGRAPH_NEW_EMBEDDING_API_BASE = "OpenAI-compatible /v1 base URL"
$env:AGRIGRAPH_NEW_EMBEDDING_API_KEY = "rotated local key"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\migrate_agrigraph_embeddings.ps1
```

该命令依次验证最小请求/usage/1024 维、停止 AgriGraph API、执行 dry-run、以 batch 10 全量重建，并要求 `documents == updated`。任一步失败时 API 保持停止或由运维显式使用 BM25 降级，禁止新旧向量混用。

没有 Baseline 时，Comparison/Gate 返回 `baseline_required`，不会生成 SHIP/WARN/BLOCK。

- 历史验证（旧数据盘）：AgriGraph Run `#53` 为 40/40，Document Run `#55` 为 1/1；这些记录不在当前数据库。
- 当前失败证据：Document Runs `#19/#20/#21` 因旧凭据登录 401 全部产生 `target_error`；Run `#22` 在认证修复后因旧项目 ID 404 失败。它们被保留，不能写成成功。
- 当前 Document：专用 `aqh_evaluator` 与 24 个冻结 Dev 解析产物已重建。Run `#29` 是 1/1 烟测；Run `#30` 保存 24/24 结果，其中 10 AUTO_PASS、11 REVIEW、3 REPROCESS，执行错误为 0，模型费用 `$0.04003916`。Run `#31` 保存 24 Baseline + 24 Candidate，Gate 为 `BLOCK`：3 个 Candidate 因目标侧尚未释放前轮 REPROCESS 文档而创建运行 `409 Conflict`，成功率相对下降 4.17 个百分点。已知 Candidate 模型费用 `$0.03550708`，3 个错误 Case 费用保持 UNKNOWN。
- 当前 provenance：两个目标的冻结 Case 与当前 dirty 源码树 SHA 均可复现；这些比较仍是相同 dirty 服务快照的稳定性评测，不能宣称不同代码提交回归。
- 当前 AgriGraph：轮换 Key 的最小请求验证通过，`qwen3.7-text-embedding` 返回 1024 维；ES 向量 `163 discovered == 163 updated`。Run `#32` 为 3/3 烟测，Run `#33` 为 40/40 Characterization，Run `#34` 为 40 Baseline + 40 Candidate 且 Gate `SHIP`。两侧成功率均 80%、目标执行错误均 0；费用保持 UNKNOWN。
