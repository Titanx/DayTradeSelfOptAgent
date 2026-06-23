# SkillOpt 理解笔记：如何用它优化 AStockAgent 的 Agent Prompt

> 基于微软研究院 SkillOpt 论文 (arXiv:2605.23904) + 开源代码 (github.com/microsoft/SkillOpt)

---

## 一、SkillOpt 是什么

**一句话**：把 Agent 的技能文档 (Markdown prompt) 当作神经网络权重来训练，但完全不碰模型参数。

### 核心映射

| 深度学习概念 | SkillOpt 文本空间对应 |
|-------------|---------------------|
| 前向传播 (Forward) | 用当前 skill 执行一批任务，收集轨迹和分数 |
| 反向传播 (Backward) | Optimizer LLM 分析错误轨迹，生成结构化编辑提案 |
| 学习率 (Learning Rate) | 编辑预算：每步最多改 N 条规则 (如 2-4 条) |
| 验证集 (Validation) | 在 held-out 日期上验证，只有严格提升才接受 |
| 动量 (Momentum) | 跨 epoch 的 slow update：保留长期稳定的编辑方向 |
| 负反馈 | Rejected-edit buffer：失败编辑供后续参考，避免重复走老路 |

### 双模型架构

```
┌──────────────────────────────────────────┐
│           SkillOpt 训练循环               │
│                                          │
│  Target Model (DeepSeek-V4)              │
│    ├─ 带着当前 Agent Prompt 执行任务       │
│    ├─ 产生 Buy/Hold 决策                  │
│    └─ 记录全部轨迹 + 实际涨跌 (奖励信号)    │
│           ↓                              │
│  Optimizer Model (更强的 LLM)             │
│    ├─ 分析 MISS/STEP 的失败轨迹            │
│    ├─ 从 minibatch 中发现系统性错误模式     │
│    ├─ 生成 add/delete/replace 编辑提案     │
│    └─ 裁剪到编辑预算 (≤4条)                │
│           ↓                              │
│  Validation Gate                         │
│    ├─ 在 held-out 日期上测试新 prompt      │
│    ├─ 命中率提升 → 接受                    │
│    └─ 没提升/变差 → 拒绝 (写入 buffer)     │
└──────────────────────────────────────────┘
```

部署时只有最终的 `best_skill.md`（300-2000 token），**零额外推理开销**。

---

## 二、核心设计原则

### 2.1 有界编辑 (Bounded Editing)

**不是让 LLM 自由重写整个 prompt，而是每步只改 2-4 条规则。**

原因：
- 无约束重写可能一次擦除已有的好规则
- 可能引入矛盾指令
- 可能过拟合到某个局部失败案例
- 版本间保持连续性，后续 optimizer 才能从版本历史中学习

### 2.2 Minibatch 分析 → 找系统性问题

**不是逐条分析单个失败案例**，那会产生"个案补丁"（只对特定股票有效）。

而是：
- 把失败案例分组（如按板块：光伏 3 次 MISS + 风电 2 次 MISS）
- 让 Optimizer 看「同一类错误反复出现」→ 生成的是**可泛化的规则**

### 2.3 验证门控 (Validation Gate)

候选 prompt 必须在 held-out 日期上跑：
- **严格大于**当前最优分数 → 接受
- 平局/下降 → 拒绝，但编辑内容存入 rejected buffer 供后续参考

这保证了 prompt 不会静默漂移退化。

### 2.4 慢速更新 (Slow Update) = 长期动量

每个 epoch 结束时，对比前后表现，将「跨 epoch 稳定提升的编辑方向」写入受保护字段。
短期波动（某一天市场异常）不会冲掉长期积累的经验。

---

## 三、如何应用到 AStockAgent

### 3.1 Agent Prompt 即 Skill 文档

当前 AStockAgent 有 5 个可优化的 Prompt：

| Agent | 文件 | 当前问题 |
|-------|------|---------|
| Bull Researcher | `agents/researchers/bull_researcher.py` | 过于保守，Buy 信号产出率 4-12% |
| Bear Researcher | 同上 | 质疑过强，压制了合理看多 |
| Research Manager | 同上 | 24h 维度裁决偏向保守 |
| Trader | `agents/trader.py` | 1% 阈值 + 流动性检查 |
| PM/Risk mgmt | `agents/risk_mgmt.py` | Aggressive/Conservative/Neutral 三方权重 |

### 3.2 SkillOpt 训练流程 (AStockAgent 版)

```
Epoch 1..N:
  Step 1: Rollout
    ├─ 用当前 prompt 跑 25 支股票 (训练集日期)
    ├─ 等待下一个交易日收盘
    └─ 产生 (决策, 实盘涨跌) 对 → 奖励信号

  Step 2: Reflect
    ├─ Optimizer LLM 分析:
    │   ├─ MISS 案例 (Buy 但跌) → 是什么导致看错?
    │   ├─ STEP 案例 (Hold 但涨) → 为什么不敢买?
    │   └─ 按 sector/error_type 分组 minibatch
    └─ 输出: 系统性失败模式 + 编辑提案

  Step 3: Edit
    ├─ 生成 add/delete/replace 操作
    ├─ 按预期效用排序
    └─ 裁剪到预算 (如 ≤3 条/Agent)

  Step 4: Gate
    ├─ 在验证集日期上跑新 prompt
    ├─ 准确率提升 → 接受
    └─ 否则 → 拒绝，写入 buffer
```

### 3.3 训练/验证集划分

```
训练集: 06-12 ~ 06-16 (4天 = 100 样本)
验证集: 06-17 ~ 06-18 (2天 = 50 样本)
测试集: 06-22 ~ 06-24 (3天 = 75 样本)
```

### 3.4 优化器模型选择

- **Optimizer (分析错误)**: 用最强模型 (DeepSeek-V4 或 GPT-5.5)，只离线运行
- **Target (执行决策)**: DeepSeek-V4，无变化，温度 0.1

---

## 四、预期的优化效果

### 当前基线

| 指标 | 值 | 问题 |
|------|:--:|------|
| Buy 命中率 | 2/3 = 67% | 可接受 |
| 踏空率 | 10/50 = 20% | 🟡 偏高 |
| 误判率 | 1/50 = 2% | ✅ |
| Buy 信号率 | 4-12% | 🟡 偏低 |

### 优化方向

1. **降低踏空**: 让 Bull/PM 在"中性偏多"环境也敢出 Buy (如 06-15 踏空 4 支大涨)
2. **消除误判**: 继续用 temperature 0.1 + 针对性 prompt 修复
3. **提升信号率**: 目标 Buy 信号率 15-25%

### 为什么一日游特别适合 SkillOpt

- **每日 25 个样本**: 一周 125 个，两周 250 个 — 足够做有统计意义的优化
- **奖励信号明确**: 24h 后实盘涨跌，没有长期不确定性
- **快速闭环**: 今天优化 → 明天验证 → 后天生效

---

## 五、实现路线图 (暂不执行)

| 阶段 | 内容 |
|------|------|
| P0 | 理解 SkillOpt 论文 + 代码 ✅ (当前) |
| P1 | 设计 AStockAgent 的 skill 文档结构 (把 prompt 格式化成 SkillOpt 可编辑的 Markdown) |
| P2 | 实现 rollout 自动化 (batchanalyze → 等待收盘 → 收集奖励) |
| P3 | 实现 reflection (Optimizer LLM 分析 MISS/STEP 生成编辑) |
| P4 | 实现 validation gate (held-out 日期自动验证) |
| P5 | 首轮 A/B 对比 (SkillOpt 优化后 vs 当前 prompt) |
