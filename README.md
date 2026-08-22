# Agent Quality Harness

Agent 的自动化评测、调用链追踪、失败回放和 CI 发布门禁平台。当前状态为 `MVP 开发中`，已安装依赖不等同于已实现功能。

## 当前实施边界

- Complete backend MVP：FastAPI、PostgreSQL/Alembic、可靠 Redis Worker、Inspect AI、HTTP/SSE、确定性 Scorer、Baseline/Candidate、Gate、失败回放、Token/Cost、持久事件与 Gate CLI。
- Verified：运行前 Dataset 哈希复核、同 Target 默认约束、pending Adapter 预检、真实 Trace ID、失败 case 回放、queued 取消、版本对比和 SHIP/WARN/BLOCK 边界。
- Pending：Vue 3 核心页面、Collector/Jaeger 端到端导出、running 取消的慢目标验收、AgriGraph/Document Autoflow 真实轮次、AG-UI、Agent Skills/OPA、DeepAgents、A2A、MCP。
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
python -m uvicorn agent_quality_harness.main:app --host 127.0.0.1 --port 8000
```

另开终端启动 Worker：

```powershell
conda activate agent-quality-gate
python -m agent_quality_harness.worker
```

API 文档：`http://127.0.0.1:8000/docs`。

## 验证

```powershell
python -m ruff check .
python -m pytest -m "not integration"
$env:AQH_RUN_INTEGRATION = "1"
python -m pytest tests/test_integration_run.py -q
python -m alembic check
```

集成测试只使用项目三的 PostgreSQL/Redis，并按本次测试创建的 ID 清理数据。

Gate CLI：

```powershell
aqh gate --run-id 123 --api-url http://127.0.0.1:8000
aqh gate --report tests/fixtures/gate-ship.json
```

`SHIP/WARN` 返回 0，`BLOCK/FAILED` 返回非零。`datasets/` 中的 80 条 core 和 20 条 stability 数据均明确标记为 Demo Fixture；两个真实系统的配置模板尚未完成 live verification。
