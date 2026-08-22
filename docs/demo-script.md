# Agent Quality Harness 面试演示脚本

目标时长：6-8 分钟。所有结果以真实 API 和持久化记录为准，Demo Fixture 会显式标记。

## 0:00-1:00 定位

说明平台解决的是 Agent 版本回归问题：Inspect AI 执行冻结数据集，HTTP/SSE Adapter 调用被测系统，OpenTelemetry 串联 Trace，Gate Engine 给出 SHIP/WARN/BLOCK。DeepAgents、A2A、MCP、Kafka 和 Kubernetes 均为后置项。

## 1:00-2:15 创建可复现运行

展示 Target、Baseline/Candidate、冻结 Dataset 和运行清单。指出清单固定数据集哈希、版本快照、配置哈希、GatePolicy、PricingSnapshot 和代码版本；运行前再次校验 case 与 dataset 哈希。

## 2:15-4:00 评测运行详情

打开 EvalRun 详情，选择一个 Candidate 失败 case。左侧展示输入、输出和确定性规则，右侧展示脱敏事件时间线和 Jaeger Trace 链接。说明未知 Token/费用保持 null，不用零冒充观测值。

## 4:00-5:15 版本对比

展示任务成功率、工具参数准确率、安全违规、P95 延迟、Token 和费用。强调关键安全违规优先 BLOCK，成功率下降超过 3 个百分点 BLOCK，延迟或成本增长超过 20% WARN。

## 5:15-6:15 失败回放

从原运行发起回放，默认只选择 Candidate 失败 case。展示 replay_of_run_id、原运行清单和选中 case 列表，原结果保持不变。

## 6:15-7:15 CI 门禁

运行 aqh gate --run-id ID。SHIP/WARN 返回 0，BLOCK/FAILED 返回非零；WARN 和 BLOCK 输出 GitHub Actions 注释。

## 7:15-8:00 边界

说明 AgriGraph 和 Document Autoflow 只通过配置作为真实被测目标，不修改原仓库。AG-UI、Skills/OPA、DeepAgents、A2A、MCP、Kafka 和 Kubernetes 未验收前保持 pending/optional。
