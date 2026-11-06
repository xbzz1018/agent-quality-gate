# 本地运行与质量检查

[返回首页](../README.md) · [工程细节](engineering-details.md)

命令从仓库根目录执行；Web 命令进入 `web/`。默认核心 Compose 使用本地 Demo Fixture，不需要真实目标凭据。

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
docker compose up -d postgres redis opa
$env:AQH_REDIS_URL = "redis://localhost:56379/0"
$env:AQH_OPA_ENABLED = "true"
python -m alembic upgrade head
"请在这里输入至少 12 位强密码" | aqh admin bootstrap --username admin --display-name "Platform Administrator" --password-stdin
python -m uvicorn agent_quality_harness.main:app --host 127.0.0.1 --port 8010
```

另开终端启动 Worker：

```powershell
conda activate agent-quality-gate
$env:AQH_REDIS_URL = "redis://localhost:56379/0"
$env:AQH_OPA_ENABLED = "true"
python -m agent_quality_harness.worker
```

另开终端启动明确命名的本地 Fake Agent：

```powershell
conda activate agent-quality-gate
python -m uvicorn agent_quality_harness.fake_http_agent:app --host 127.0.0.1 --port 8020
```

启动 Vue 开发服务器（`/api` 自动代理到端口 8010）：

```powershell
cd web
npm ci
npm run dev
```

开发 Web：`http://127.0.0.1:5173`。API 文档：`http://127.0.0.1:8010/docs`。平台不内置默认密码，首次启动必须通过上面的 stdin 命令创建管理员。

推荐用存储受控的 Compose 核心拓扑。首次运行加 `-Build`；已有镜像时可省略此参数：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_closeout_stack.ps1 -Build
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

本地集成测试使用本仓库的 PostgreSQL、Redis 和 OPA，并按本次测试创建的组织与队列清理数据。运行测试的终端也须设置上面的 Redis 地址；如果调整了 Compose 端口，同步修改本地连接配置。CI 使用独立服务与独立环境变量。


## 最短演示路径

1. 启动核心栈并创建管理员，打开 `http://127.0.0.1:5174`。
2. 点击“初始化 Demo Fixture”，创建明确标记的 HTTP Fake Agent、80 条冻结样例、Baseline/Candidate 和策略。
3. 创建并等待 Worker 执行 Baseline 和 Candidate；Fixture 初始化本身不生成运行成绩。
4. 进入版本对比和失败 Case，检查规则、Trace 与回放，再查看 Gate 原因。

Demo Fixture 证明链路可执行，不代表真实 Agent 质量。没有 Baseline 的 Candidate-only 运行返回 `baseline_required`；真实目标验收的日期与源码边界见[历史记录](current-target-verification.md)。
