# MailKnow V5.2 — 验收测试计划

> 版本：V5.2 | 日期：2026-05-02 | 执行周：W15-W16
> 基于：开发计划 W15 测试周要求 + 实测问题反馈

---

## 一、测试数据集准备

### 1.1 Gate分流样本（2000封）

| 行业 | 数量 | 来源 | 内容 |
|------|------|------|------|
| 互联网 | 2000 | Enron数据集 | 技术/产品/行政/审批邮件 |

**当前状态**：✅ 已生成 `gate_samples.json`（2000封）
**分类分布**：G0(43) / G1(191) / G2(58) / G3(1673) / G4(35)

**待补充**：行业分布不均（仅Enron互联网行业），需补充：
- 金融行业审批/报价邮件（400封）
- 制造业供应链邮件（400封）
- 零售业订单/客服邮件（300封）

### 1.2 审批边界样本（200封）⚠️ 需扩展

| 类型 | 计划数量 | 当前数量 | 待补充 |
|------|---------|---------|--------|
| 直接审批 | 50 | 2 | 48 |
| CC审批 | 50 | 2 | 48 |
| 已完成通知 | 50 | 2 | 48 |
| 系统转发 | 50 | 4 | 46 |

**当前状态**：⚠️ 仅10条样本
**存放路径**：`tests/datasets/approval_samples.json`

### 1.3 脱敏测试集（50封）

| 类型 | 数量 | 状态 |
|------|------|------|
| 人名脱敏 | 15 | ✅ |
| 手机脱敏 | 10 | ✅ |
| 邮箱脱敏 | 10 | ✅ |
| 身份证脱敏 | 5 | ✅ |
| 金额脱敏 | 5 | ✅ |
| 密码脱敏 | 5 | ✅ |

**当前状态**：✅ 已生成 `sensitive_samples.json`（50封）

### 1.4 搜索测试集（30条）

| 类型 | 数量 | 状态 |
|------|------|------|
| 实体查询 | 10 | ✅ |
| 语义查询 | 10 | ✅ |
| 结构化查询 | 10 | ✅ |

**当前状态**：✅ 已生成 `search_queries.json`（30条）

### 1.5 周报盲测集（4份）

**当前状态**：❌ 未准备（需4位标注员手写周报对比）

---

## 二、降级测试（4场景）⚠️ 脚本需修复

### 2.1 当前问题

**问题**：`test_degradation.py` 导入了不存在的 `withFallback` 函数，实际模块中是 `WithFallback` 类。

```python
# 错误导入
from llm.fallback import withFallback, FallbackConfig

# 正确导入
from llm.fallback import WithFallback, FallbackConfig
```

**另外**：`FallbackConfig` 的参数名与测试脚本不一致：
- 测试脚本用 `timeout`, `fallback_value`, `fallback_handler`, `backoff_factor`, `on_fallback`
- 实际类用 `max_retries`, `retry_delay_base`, `retry_delay_max`, `timeout_per_retry`, `strategy`

### 2.2 修复方案

重写 `test_degradation.py`，基于 `WithFallback` 类的异步 API：

| 场景 | 模拟条件 | 预期行为 | 通过标准 |
|------|---------|---------|---------|
| **LLM完全不可用** | mock LLMClient 抛异常 | 自动切换纯GBrain模式 | `result.used_fallback == True` |
| **LLM超时10s** | mock LLMClient 超时 | `WithFallback` 降级 | `result.used_fallback == True`, `result.fallback_reason` 含 "timeout" |
| **LLM部分失败** | 50%请求mock抛异常 | 重试+降级混合 | 成功请求正常，失败请求降级 |
| **间歇断网** | mock 交替成功/失败 | 自动重试 | 最终返回结果或降级 |

### 2.3 测试脚本

```python
# 修复后的降级测试
import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from llm.fallback import WithFallback, FallbackConfig, FallbackStrategy
from llm.client import LLMClient, LLMResponse, LLMProvider

@pytest.fixture
def fallback():
    """创建 WithFallback 实例"""
    llm = AsyncMock(spec=LLMClient)
    config = FallbackConfig(max_retries=2, timeout_per_retry=10.0)
    return WithFallback(llm_client=llm, config=config), llm

@pytest.mark.asyncio
async def test_llm_unavailable(fallback):
    """LLM完全不可用→降级到本地"""
    wf, llm = fallback
    llm.complete.side_effect = Exception("Service unavailable")
    
    result = await wf.call(
        prompt="Classify this email",
        local_fallback=lambda p, s: '{"is_approval": false}',
    )
    
    assert result.used_fallback == True
    assert result.content == '{"is_approval": false}'

@pytest.mark.asyncio
async def test_llm_timeout(fallback):
    """LLM超时→自动降级"""
    wf, llm = fallback
    llm.complete.side_effect = asyncio.TimeoutError()
    
    result = await wf.call(
        prompt="Test prompt",
        local_fallback=lambda p, s: 'fallback_result',
    )
    
    assert result.used_fallback == True

@pytest.mark.asyncio
async def test_partial_failure(fallback):
    """LLM部分失败→重试成功"""
    wf, llm = fallback
    llm.complete.side_effect = [
        Exception("Temp error"),  # 第1次失败
        LLMResponse(              # 第2次成功
            content='{"result": "ok"}',
            provider=LLMProvider.OPENAI,
            model="gpt-4o-mini",
            tokens_in=100,
            tokens_out=50,
        ),
    ]
    
    result = await wf.call(prompt="Test")
    assert result.used_fallback == False
    assert result.retries == 1
```

---

## 三、脱敏安全测试

### 3.1 当前结果

| 测试项 | 结果 | 说明 |
|--------|------|------|
| 手机号脱敏 | ✅ PASS | 3/3 |
| 邮箱脱敏 | ✅ PASS | 3/3 |
| 身份证脱敏 | ✅ PASS | 2/2 |
| 金额脱敏 | ✅ PASS | 3/3（已修复regex） |
| 密码脱敏 | ✅ PASS | 3/3 |
| 人名脱敏 | ✅ PASS | 3/3 |
| 端到端测试 | ❌ FAIL | 49/50（1条人名未脱敏） |

### 3.2 待修复

**人名脱敏端到端1条失败**：
- 可能原因：人名在特定上下文中未被正确识别
- 修复方向：检查 `sensitive_samples.json` 中失败的测试用例，增强人名匹配规则

### 3.3 新增测试：脱敏上下文隔离

| 测试项 | 方法 | 通过标准 |
|--------|------|---------|
| 拆段脱敏效果 | 对比全文脱敏vs拆段脱敏的审批识别Precision | 损失≤10pp |
| 脱敏-还原一致性 | 脱敏后→还原→与原文一致 | 100%一致 |

---

## 四、性能测试

### 4.1 当前结果 ✅ 全部通过

| 指标 | 目标 | 实测 | 状态 |
|------|------|------|------|
| Gate分流 | - | 2,310,063 封/秒 | ✅ |
| 1K封插入 | - | 204,411 封/秒 | ✅ |
| Search P95 | <500ms | 0.1ms | ✅ |
| 5万封插入 | <5min | 0.3秒 | ✅ |

### 4.2 新增测试：Token成本压测

| 用户类型 | 日均邮件 | 预算 | 验证方法 |
|---------|---------|------|---------|
| 轻度用户 | 20封 | $0.10/天 | 统计Token消耗 |
| 中度用户 | 50封 | $0.25/天 | 统计Token消耗 |
| 重度用户 | 200封 | $0.50/天 | 统计Token消耗 |

**测试方法**：模拟不同日均邮件量下的Token消耗，验证月成本 ≤ $9

---

## 五、E2E场景测试 ❌ 待编写

### 5.1 审批闭环测试

```
同步邮件 → Gate分流 → Tier2筛选 → Tier4精筛 → 审批卡片 → 用户操作 → 归档
```

**验证点**：
- Gate分流正确
- 审批识别准确
- 卡片展示正确
- 用户操作生效
- 归档成功

**脚本路径**：`tests/e2e/test_approval_flow.py`

### 5.2 周报生成测试

```
GBrain查询 → 聚类 → LLM总结 → 周报编辑器 → 导出
```

**验证点**：
- 事实准确率>90%
- 无预测内容（不含"下周计划"）
- 编辑器可修改
- 导出功能正常

**脚本路径**：`tests/e2e/test_report_generation.py`

### 5.3 场景推荐测试

```
冷启动 → 首日导入 → 首周 → 首月
```

**验证点**：
- 各阶段推荐策略正确切换
- 推荐边界控制（每日≤5张）
- 反馈飞轮生效

**脚本路径**：`tests/e2e/test_scene_recommendation.py`

### 5.4 知识库查询测试

```
"和A公司的往来邮件" → 实体识别 → Hybrid Search → 结果展示
```

**验证点**：
- 实体识别准确
- 搜索结果相关
- 展示清晰

**脚本路径**：`tests/e2e/test_knowledge_search.py`

---

## 六、审批边界测试

### 6.1 当前结果

| 测试项 | 结果 | 说明 |
|--------|------|------|
| border_cc_approval | ❌ FAIL | 预期 type=cc, 实际 type=ApprovalType.DIRECT |
| border_completed_notification | ✅ PASS | |
| border_system_forward | ❌ FAIL | 系统转发被判为直接审批 |
| border_confirmation_not_approval | ✅ PASS | |
| border_english_approval | ✅ PASS | |
| border_mass_cc_approval | ✅ PASS | |
| border_urgent_approval | ✅ PASS | |
| border_rejection_notification | ✅ PASS | |
| border_approval_with_discussion | ✅ PASS | |
| border_pure_discussion | ✅ PASS | |

**通过率**：9/10

### 6.2 待修复

1. **CC审批类型判定**：`ApprovalDetector` 未区分 `cc` 类型审批，需在 `ApprovalType` 中增加 CC 子类型或在 `detector.py` 中添加 CC 判断逻辑
2. **系统转发判定**：OA系统转发的审批邮件被误判为直接审批，需增加系统转发特征识别

### 6.3 待扩展样本

当前10条 → 需扩展至200条（各类型50条），覆盖更多边界场景

---

## 七、Token预算测试 ⚠️ 脚本需修复

### 7.1 当前问题

**问题1**：测试脚本用 `BudgetConfig(monthly_budget_usd=9.0, daily_budget_usd=0.30)` 参数名，实际 `BudgetConfig` 参数名为 `monthly_cost_limit`, `daily_cost_limit`

**问题2**：测试脚本引用 `TokenBudgetV2` 类，实际类名是 `TokenBudgetController`

**问题3**：测试脚本调用的方法（`record_usage`, `check_budget`, `get_degradation_level`, `get_monthly_usage`, `generate_monthly_report`）与实际 API 不匹配

### 7.2 修复方案

重写 `test_token_budget_e2e.py`，基于 `TokenBudgetController` 的实际 API：

```python
from llm.token_budget_v2 import TokenBudgetController, BudgetConfig, DegradationLevel

# 正确的初始化
config = BudgetConfig(
    monthly_cost_limit=9.0,
    daily_cost_limit=0.50,
    monthly_token_limit=10_000_000,
    daily_token_limit=500_000,
)
budget = TokenBudgetController(config)

# 正确的API调用
budget.check(estimated_tokens=5000, task_type="general")  # 预算检查
budget.record(tokens_in=500, tokens_out=200, cost=0.002, provider="openai", task_type="general")  # 记录消耗
budget.degradation_level  # 获取降级级别（属性，非方法）
budget.get_summary()  # 获取使用摘要
budget.estimate_cost(tokens_in=500, tokens_out=200)  # 成本估算
```

### 7.3 测试场景

| 场景 | 操作 | 预期结果 |
|------|------|---------|
| 正常使用 | 日均50封邮件的Token消耗 | `degradation_level == NORMAL` |
| 超限预警 | 消耗达到80%月预算 | `degradation_level == WARNING` |
| 降级触发 | 消耗达到95%月预算 | `degradation_level == DEGRADED` |
| 完全降级 | 月预算用尽 | `degradation_level == PURE_GBRAIN`, `check() == False` |
| 成本估算 | 估算请求成本 | 与实际偏差<10% |
| 使用摘要 | 获取 UsageSummary | daily/monthly 数据正确 |
| 持久化 | 写入SQLite后重启 | 数据恢复正确 |

---

## 八、前端交互测试（Playwright）❌ 待编写

### 8.1 关键路径

| 路径 | 步骤 | 验证点 |
|------|------|--------|
| 邮件同步 | 启动→配置账号→同步 | 邮件列表展示 |
| Gate分流 | 查看Gate 4档视图 | 分类正确 |
| 审批操作 | 点击审批卡片→批准 | 操作生效 |
| 周报生成 | 场景卡片→生成周报 | 周报展示 |
| 搜索 | 输入查询→查看结果 | 结果相关 |

### 8.2 UI响应测试

- 点击响应<200ms
- 列表滚动流畅
- 无UI阻塞

### 8.3 脚本路径

`tests/e2e/test_frontend_interaction.spec.ts`

---

## 九、测试执行排期

| 优先级 | 测试类型 | 状态 | 预计耗时 |
|--------|---------|------|---------|
| **P0** | 修复降级测试脚本 | ❌ 需修复 | 1h |
| **P0** | 修复Token预算测试脚本 | ❌ 需修复 | 1h |
| **P0** | 编写E2E审批闭环测试 | ❌ 未编写 | 1.5h |
| **P0** | 编写E2E周报生成测试 | ❌ 未编写 | 1h |
| **P0** | 编写E2E场景推荐测试 | ❌ 未编写 | 1h |
| **P0** | 编写E2E知识库查询测试 | ❌ 未编写 | 1h |
| **P1** | 扩展审批边界样本至200封 | ⚠️ 仅10条 | 2h |
| **P1** | 修复脱敏测试1条未通过 | ⚠️ | 0.5h |
| **P1** | 修复审批边界测试2条未通过 | ⚠️ | 1h |
| **P2** | 编写前端交互测试 | ❌ | 4h |
| **P2** | Token成本压测 | ❌ | 2h |

---

## 十、测试通过标准

| 测试类型 | 通过标准 | 当前状态 |
|---------|---------|---------|
| 降级测试（4场景） | 全部通过 | ❌ 脚本需修复 |
| 脱敏安全测试 | 7/7通过（当前6/7） | ⚠️ 需修复1条 |
| 脱敏上下文隔离 | 损失≤10pp | ❌ 未编写 |
| 性能测试 | 全部达标 | ✅ 4/4通过 |
| 审批边界测试 | 10/10通过（当前9/10） | ⚠️ 需修复1条 |
| Token预算测试 | 全部通过 | ❌ 脚本需修复 |
| E2E场景测试 | 4个场景全流程通过 | ❌ 未编写 |
| 前端交互测试 | 关键路径通过 | ❌ 未编写 |
| **Bug数量** | P0=0, P1<3 | - |

---

> **验收测试计划 V2** — 2026-05-02 更新
> **关键变化**：
> 1. 发现降级测试+Token预算测试脚本与实际代码API不匹配，需重写
> 2. 新增4个E2E场景测试
> 3. 审批边界样本需从10条扩展至200封
> 4. 脱敏测试1条+审批边界测试1条待修复
