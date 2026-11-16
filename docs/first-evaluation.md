# 第一次评测：用 Demo 对比两个版本

[返回首页](../README.md) · [运行手册](runbook.md) · [项目案例](project-case.md)

这条路径使用本地 HTTP Fake Agent 和 80 条合成样例，帮助你熟悉创建运行、检查 Case 和解释 Gate。首次体验不需要连接真实 Agent 或配置模型 API Key。

## 1. 等待核心服务就绪

从首页的 PowerShell 命令启动核心栈后，在仓库根目录检查：

```powershell
docker compose ps
```

确认 PostgreSQL、Redis、OPA、API、Worker、Fake Agent 和 Web 均已启动并显示 `healthy`，再继续。首次构建和数据库迁移可能需要等待；启动脚本返回不等于服务全部就绪。

## 2. 创建管理员并登录

首次使用时，执行以下命令。密码以隐藏输入读取，通过标准输入传给容器中的 CLI；请设置至少 12 位密码。

```powershell
$OutputEncoding = [System.Text.UTF8Encoding]::new()
$adminPassword = Read-Host "设置 AQH 管理员密码（至少 12 位）" -AsSecureString
$adminCredential = [System.Management.Automation.PSCredential]::new("admin", $adminPassword)
$adminCredential.GetNetworkCredential().Password | docker compose exec -T api aqh admin bootstrap `
  --username admin --display-name "Platform Administrator" --password-stdin
Remove-Variable adminCredential, adminPassword
```

打开 <http://127.0.0.1:5174>，用 `admin` 和刚设置的密码登录。已有管理员时直接登录，不要重复执行初始化命令。

## 3. 初始化 Demo 配置

进入「被测目标」，点击 **Demo Fixture**。成功后会出现 `Demo Fixture Agent`，并创建以下资源：

| 资源 | 在创建运行时选择 |
| --- | --- |
| 被测目标 | `Demo Fixture Agent` |
| 冻结数据集 | `agent-quality-harness-demo-core`，版本 `v1`，80 cases |
| Baseline | `baseline` |
| Candidate | `candidate` |
| Gate Policy | `Demo Fixture Release Gate`，版本 `v1` |
| Pricing Snapshot | `demo-fixture/deterministic-fake-agent`，版本 `v1` |

这个操作只准备配置，不会创建运行或填入成绩。再次点击会复用已有 Demo 资源。

## 4. 在一次运行中选择两个版本

进入「评测运行」，点击 **创建运行**，按上表选择字段，再点击 **进入评测队列**。

两个版本在同一次运行中使用同一个冻结数据集。首次做版本对比时，请填写 Baseline；留空会创建 Candidate-only 特征评测，无法查看版本对比或发布门禁。

进入运行详情后，等待状态从 `Queued` / `Running` 变为 `Completed`，核对 Case 进度为 `80 / 80`。进度按样例计数，结果列表则分别包含 Baseline 和 Candidate 的执行结果，完整对比应有两侧各 80 条结果。

## 5. 先看差异，再看原因

1. 点击 **版本对比**，检查成功率、工具参数准确率、P95 延迟和平均成本，留意 `UNKNOWN` 等缺失项。
2. 回到运行详情选择一条 Case，查看输出、最终动作、规则报告、失败类型和事件。存在 Candidate 失败 Case 时，可点击 **回放失败 Case**，创建新的回放运行。
3. 点击 **查看门禁**，一起阅读 `SHIP / WARN / BLOCK`、原因码和触发规则。`Completed` 只说明执行结束；运行完成后仍可能被门禁阻断。

Demo 的价格是合成价格，结果只适用于这组样例。无需为了得到 `SHIP` 而反复运行；出现警告或阻断时，应先查看原因。Jaeger 调用链需要另行启用观测服务，默认核心栈不包含 Jaeger。

## 卡住时从哪里查

| 现象 | 先检查 |
| --- | --- |
| 页面打不开或登录请求失败 | `docker compose ps`，再看 `docker compose logs --tail 100 api web`；确认使用 Compose 端口 `5174` |
| 初始化提示 `username already exists` | 直接使用已有账号登录；此命令不能重置密码 |
| 一直停在 `Queued` | `docker compose logs --tail 100 worker redis`，确认 Worker 健康并连接到队列 |
| 运行 `Failed` 或 Case 有执行错误 | 先看运行事件和失败类型，再看 `docker compose logs --tail 100 worker fake-agent` |
| 对比页提示需要 Baseline | 新建一次包含 `baseline` 和 `candidate` 的运行 |
| 成本为 `UNKNOWN` | 检查运行是否选择价格快照、结果是否包含用量；缺失值不能当作零费用 |

结束体验后运行 `docker compose down`，保留管理员和历史运行。端口调整、开发模式与完整检查命令见[运行手册](runbook.md)。
