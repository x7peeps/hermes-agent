# RFC: 自动化任务纠偏建议系统 (Task Optimization Advisor)

## 摘要

为 Hermes Agent 添加**任务级自我诊断与优化建议**能力，使定时任务能够自动分析执行结果、识别问题模式，并主动向用户推荐改进方案。

## 背景

当前 Hermes 的 cron 系统具备：
- ✅ 定时任务执行
- ✅ 交互级学习 (Background Review)
- ✅ Cron 推荐 (Suggestions)

但缺少：
- ❌ **任务执行结果的诊断机制**
- ❌ **性能分析**（API 调用数、延迟、超时）
- ❌ **自动化优化建议管道**

## 目标

实现"执行 → 诊断 → 建议 → 改进"的闭环：

```
定时任务执行 → 记录结果 → AI分析 → 优化建议 → 用户确认 → 自动优化
```

## 架构设计

### 1. 数据采集层

```python
# 任务执行指标采集
class TaskMetrics:
    execution_time_ms: int      # 执行时长
    api_calls: int              # API 调用次数
    errors: List[Error]          # 错误列表
    timeout_count: int           # 超时次数
    success_rate: float          # 成功率
```

### 2. 分析引擎

```python
# 5 维分析框架
class TaskOptimizer:
    def analyze(self, metrics: TaskMetrics) -> OptimizationReport:
        # 效率分析
        # 智能化分析
        # 覆盖分析
        # 稳定性分析
        # 预防分析
```

### 3. 建议生成

```python
# 建议类型
class OptimizationSuggestion:
    priority: str          # high/medium/low
    dimension: str         # efficiency/intelligence/coverage/stability/prevention
    issue: str             # 问题描述
    recommendation: str    # 改进建议
    code_location: str     # 代码位置
    estimated_impact: str  # 预期效果
```

### 4. 与现有系统集成

| 现有能力 | 集成方式 |
|----------|----------|
| Background Review | 共享诊断数据，统一优化入口 |
| Suggestions | 优化建议可转化为 cron suggestion |
| Memory | 从 Memory 学习用户偏好 |

## 实现方案

### Phase 1: 核心骨架

- `cron/task_metrics.py` - 任务指标采集
- `cron/task_optimizer.py` - 分析引擎
- `cron/optimization_suggestions.py` - 建议生成

### Phase 2: 分析能力

- 效率分析：执行时间、API 调用优化
- 智能化分析：自动决策点识别
- 覆盖分析：遗漏场景检测

### Phase 3: 自动化改进

- 用户确认后自动应用优化
- 集成到 cron 执行流程

## 示例用例

### 用例 1: GitHub PR 监控优化

**问题**：串行 API 调用导致超时

**分析**：
```
效率维度: API调用30次，耗时60秒
建议: 切换到 GraphQL 批量获取
```

**效果**：执行时间从 60s → 8s

### 用例 2: Token 失效预警

**问题**：Token 失效导致任务中途失败

**分析**：
```
稳定性维度: Token无预检查机制
建议: 增加 Token 健康检查
```

**效果**：提前发现失效，避免中途失败

## 验收标准

1. ✅ 定时任务执行后可自动生成优化建议
2. ✅ 建议包含量化指标（命中率、延迟、超时率）
3. ✅ 建议可解释、可回滚
4. ✅ 与 Background Review 协同工作

## 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 过度诊断 | 仅在指标偏离阈值时触发 |
| 误建议 | 用户确认后执行，自动回滚能力 |
| 性能开销 | 分析异步执行，不阻塞主任务 |

## 相关 Issue/PR

- 关联 Background Review: `agent/background_review.py`
- 关联 Cron Suggestions: `cron/suggestions.py`

## 作者

- Author: @x7peeps
- Date: 2026-07-10
