# Agent Quality Harness：一次版本变更如何决定是否发布

[返回首页](../README.md) · [本地体验](runbook.md) · [历史验证来源](current-target-verification.md)

## 问题与个人工作

Agent 换模型、提示词或工具后，单看几条回答很难判断能否发布。失败可能来自输出质量，也可能是目标服务报错、数据改变或成本缺失；把它们混在一个平均分里，会掩盖真正的回退。

我将被测 Agent 抽象为有版本的 Target，把数据冻结、评测执行、确定性评分、Trace、失败回放和发布门禁连接成独立控制面。平台保存每条 Case 的结果和失败类型，并在运行前复核数据完整性；Web 用于对比、排查和查看 Gate 原因。

## 操作路径

1. 注册 Target、Baseline / Candidate 和冻结 Dataset。
2. Worker 领取 EvalRun，Inspect AI 执行 Case 并发与评分。
3. 进入运行详情，核对结果数、failure_type、规则报告与 Trace。
4. 对比两侧指标，回放失败 Case，再按版本化策略得到发布决定。

无凭据体验使用明确标记的 HTTP Fake Agent 和合成 Fixture。启动与操作步骤见[运行手册](runbook.md)，初始化操作不代表运行已经完成。

## 取舍

**冻结数据和版本，明确对比条件。** 运行前重新校验 Dataset/Case 哈希，防止“同名数据集”已悄悄改变。被 EvalRun 引用的版本绑定也不能继续修改。

**平台与被测 Agent 分开部署。** Inspect AI 管理评测执行，Adapter 调用外部 Target，平台保存结果与决策。DeepAgents、协议 Fixture 与业务 Agent 都是被测对象或适配器。

**确定性规则先给出可重复判定。** 数据格式、证据映射、安全约束与发布门禁先由规则检查。LLM Judge 可以补充主观质量，不能覆盖硬性证据和安全规则。

**费用未知时保留 UNKNOWN。** 没有统一用量字段或目标调用失败时，费用未必可得。记录 UNKNOWN，避免把缺失数据误当作低成本；要求费用预算时不能据此自动授权。

## 历史案例：完成运行也可能 BLOCK

以下来自 **2026-08-26 的服务快照记录**，原始 provenance 见[目标验证记录](current-target-verification.md)。目标源码当时有未提交修改，使用源码树 SHA 标识；这些不是不同 Git 提交的回归成绩，也没有在本次重新运行。

| 记录 | 实际观察 | 如何解释 |
| --- | --- | --- |
| AgriGraph Run #34 | 40 Baseline + 40 Candidate；两侧成功率均 80%，执行错误均 0；Gate SHIP | 在当时数据与策略下没有触发回退；SHIP 不等于 100% 正确 |
| 文档目标 Run #31 | 共 48 条结果；Candidate 有 3 个 409 Conflict；成功率下降约 4.17 个百分点，阈值为 3 | 虽然结果已收集完整，执行错误和相对下降仍触发 BLOCK |
| 同一文档目标费用 | Candidate 已知费用 USD 0.03550708，3 个错误 Case 费用 UNKNOWN | 不能把已知费用当作精确总费用 |

这个失败案例说明：Run completed、结果数量完整、断言通过、目标执行成功和最终 Gate 是不同条件，必须沿 Case 与原因码一起检查。

## 交付与已知限制

交付包括 FastAPI/Worker、Vue 控制台、冻结数据与规则、Gate CLI、Compose 和验证脚本。默认核心栈可独立运行，观测、协议和 Kafka 通过 profile 启用。

CI 提供规则、数据库/队列集成、迁移与前端构建检查；历史真实目标结果只证明对应快照。Kubernetes kind/HPA、公网高可用仍未完成实际验收，静态 manifest 和普通 CI 不能代替这些验证。

## 代码入口

| 关注点 | 入口 |
| --- | --- |
| 数据冻结、门禁与失败类型的验证 | [实现与测试对应表](traceability.md) |
| 默认服务和可选 profile | [docker-compose.yml](../docker-compose.yml) |
| Baseline / Candidate 门禁规则 | [test_gates.py](../tests/test_gates.py) |
| Worker 执行与回放集成验证 | [test_integration_run.py](../tests/test_integration_run.py) |
| Web 版本对比与运行详情 | [ComparisonView.vue](../web/src/views/ComparisonView.vue)、[RunDetailView.vue](../web/src/views/RunDetailView.vue) |
