# SkillOpt + EvoSkill：双层技能自进化架构

> DayTradeSelfOptAgent 项目的核心方法论，结合 Microsoft SkillOpt 的行级编辑优化与 Sentient EvoSkill 的结构性发现，形成「**先精修，后重构**」的双层自进化流水线。

---

## 一、SkillOpt — 文本空间的梯度下降

### 1.1 核心思想

**SkillOpt** (Microsoft, 2026) 将深度学习训练范式映射到 Agent Skill 优化：

| 深度学习概念 | SkillOpt 映射 |
|:--|:--|
| 模型参数 θ | Skill 文档中的自然语言规则 |
| 损失函数 L | 回测准确率 (HIT + AVOID) |
| 梯度 ∇ | LLM 对错误模式的文本反馈 |
| 学习率 α | 每轮允许的编辑数量 (top-k) |
| 验证集 | Gate 机制：新旧 accuracy 对比 |
| 过拟合 | 拒绝单例编辑，仅 minibatch 触发 |

一句话：**不修改模型权重，而是让模型读取的 prompt 文档像模型参数一样被优化。**

### 1.2 三步管线

```
Rollout → Reflect → Update → Validate
```

- **Rollout (采集器)**：让 Agent 在训练集上运行，收集 (预测, 实盘, 辩论轨迹) 三元组
- **Reflect (优化器)**：LLM 分析错误模式，输出带理由的编辑提案 (`edits.json`)
- **Aggregate (聚合器)**：合并语义相似编辑，去重 >50% 重叠的提案
- **Select (筛选器)**：四维评分（错误严重程度 40 + 规则具体度 25 + 操作优先级 20 + 目标优先级 15），只保留 top-k
- **Update (应用器)**：写入 `<!-- SKILLOPT-EDITABLE -->` 区域
- **Validate (门控)**：新旧 accuracy 对比，退化则回滚

### 1.3 关键约束

```
- 仅编辑 <!-- SKILLOPT-EDITABLE --> 标记内的行
- 仅支持 add / delete / replace 三种操作
- 不创建新文件，不修改 Agent 架构
- 编辑前后自动 Git snapshot
```

---

## 二、EvoSkill — 能力空隙的结构性发现

### 2.1 核心思想

**EvoSkill** (Sentient, 2026) 解决一个 SkillOpt 无法触及的问题：**如果现有 agent 架构本身就缺能力怎么办？**

它的创新在于将技能发现的抽象层从「修改现有规则」提升到「创造新能力模块」：

| 传统优化 | EvoSkill |
|:--|:--|
| 改已有 prompt | **创建全新 skill 文件夹** |
| 行级编辑 | **文件夹级重构** (SKILL.md + 脚本 + 参考材料) |
| 单 Agent 模式 | **三体协作** (Executor / Proposer / Skill-Builder) |
| 版本覆盖 | **Pareto 前沿集合 G** (top-k 精英池) |

### 2.2 三体架构

```
Executor ──→ 运行轨迹 ──→ 得分
                              │
                   得分 < 阈值? ──yes──→ Proposer
                              │              │
                              │         ┌────┴────┐
                              │         │ 诊断失败  │
                              │         │ 审计现有  │
                              │         │ 决策:新建 │
                              │         │   或编辑  │
                              │         └────┬────┘
                              │              │ proposal π
                              │              ▼
                              │       Skill-Builder
                              │              │
                              │     ┌───────┴───────┐
                              │     │ 物化为完整文件夹 │
                              │     │ SKILL.md        │
                              │     │ triggers.yaml   │
                              │     │ helpers/*.py    │
                              │     └───────┬───────┘
                              │              │ candidate p̃
                              │              ▼
                              │         验证集评估
                              │              │
                              │     ┌───────┴───────┐
                              │     │ score > 最弱?  │
                              │     │ → 加入前沿 G  │
                              │     │ → 替换最弱成员 │
                              │     └───────────────┘
```

### 2.3 发现 vs 编辑的决策逻辑

Proposer 询问两个问题：

1. **能力缺口 (Capability Gap)**？现有 skills 里没有任何一条覆盖这个失败模式 → **创建新技能**
2. **能力不足 (Capability Deficiency)**？某个 skill 有相关规则但不完整/错误 → **编辑已有技能**

决策时参考**反馈历史 H**，避免重复提案或重蹈覆辙。

---

## 三、本项目的双层结合

### 3.1 完整流水线

```
┌────────────────── SkillOpt 层 (每轮自动) ──────────────────┐
│                                                              │
│  collector → debate_logger → optimizer → aggregate → select │
│                                                              │
│                              ↓                               │
│                          applier 写入 skill                  │
│                                                              │
│                              ↓                               │
│                         记录 accuracy                        │
│                                                              │
└──────────────────────────────────────────────────────────────┘
                                ↓
                    检测是否收敛 (pipeline_history)
                                ↓
                    最近 3 轮 accuracy 波动 < 2%?
                                ↓
                    ┌── yes ──→ EvoSkill 层触发
                    │
                    │   evolve.py:
                    │     1. 加载全部辩论轨迹
                    │     2. LLM 深度分析 10 条错误样本
                    │     3. 审计 8 个 skill 的能力覆盖
                    │     4. 诊断: 结构性缺口 vs 规则不足
                    │     5. 输出 discovery.json
                    │
                    │     ↓ (人工审核)
                    │
                    │   needs_structural_change = True?
                    │     ├─ new_agent → 创建新 skill + 注册节点
                    │     ├─ new_section → 在现有 skill 加新章节
                    │     └─ merge → 合并冗余 agent
                    │
                    └── no ──→ 继续 SkillOpt 微调
```

### 3.2 设计原则

| 问题 | 方案 |
|:--|:--|
| SkillOpt 反复出同样的编辑？ | `aggregate.py` 去重 + `select.py` 评分淘汰 |
| 优化到平台期怎么办？ | 收敛检测触发 `evolve.py` |
| EvoSkill 误判怎么办？ | 人工审核 + 不自动 apply |
| 新 skill 会不会退化成只写不修？ | 新 skill 同样带 `<!-- SKILLOPT-EDITABLE -->`，下次 SkillOpt 循环自动接管 |

### 3.3 两种模式的互操作

```
SkillOpt 能做的                 EvoSkill 能做的
─────────────                  ─────────────
改 bull_researcher 的规则      新建 reversal_analyst
改 portfolio_manager 的门槛    提出 merge_bull_bear  
改 research_manager 的判断条件 新建 sector_rotation_analyst
改 trader 的仓位限制           新建 market_breadth 分析节点
```

**两者互不冲突**。EvoSkill 创建的新 skill 天然带 `<!-- SKILLOPT-EDITABLE -->` 标记，下一轮 SkillOpt 就可以开始编辑它。

---

## 四、实际案例

### 4.1 SkillOpt 层：视觉板块超跌反弹规则

**触发**：06-23 预测 → 06-24 实盘，准确率 60%，10 次 STEP 漏判

**Optimizer (DeepSeek V4) 分析**：
> "Vision sector has 3 STEP, indicating systemic issue: Bull/Bear/PM missing rebound signals"

**输出编辑 (edits.json)**：

```json
{
  "action": "add", "file": "bull_researcher", "section": "rules",
  "new": "视觉板块（002415/002236/603501）连续调整后，关注北向资金回流和机构调研信号，超跌反弹概率高"
}
{
  "action": "add", "file": "portfolio_manager", "section": "decision_rules",
  "new": "如果 Bull 给出明确超跌反弹信号且 Bear 无重大流动性风险，即使预期涨幅在0.8-1.0%也可考虑Buy"
}
{
  "action": "add", "file": "research_manager", "section": "decision_framework",
  "new": "视觉板块出现连续3日以上调整且尾盘有资金介入迹象时，优先考虑Buy"
}
```

**效果**：定价门槛从 1.0% 降到 0.8%，视觉板块获得专属反弹规则。

---

### 4.2 Evolve 层：发现 reversal_analyst

**触发**：SkillOpt 优化后，pipeline_history 反映连续优化仍无法突破 STEP 瓶颈

**LLM 分析 10 条错误轨迹 + 8 个 skill 的能力矩阵后诊断**：

> "All 10 errors are false negatives: the system consistently predicts Hold when actual returns exceed +1%. The core failure is that the pipeline lacks an agent capable of independently assessing and advocating for high-probability short-term reversal trades. The Bull Researcher is too easily overridden by Bear/Conservative risks."

**提案 (discovery.json)**：

```json
{
  "type": "new_agent",
  "name": "reversal_analyst",
  "reason": "Bull Researcher 太容易被 Bear/风控压制，需要独立评估反弹的 agent",
  "capabilities": [
    "识别超卖条件 (RSI<30, KDJ 负值, 布林下轨)",
    "检测尾盘放量企稳",
    "评估板块轮动信号",
    "量化反弹概率 (历史相似模式)",
    "提供明确入场/止损价位"
  ],
  "sample_rules": [
    "rule: 使用定量标准: RSI<30, KDJ J<0, 价格在布林下轨 2% 内",
    "rule: 对每个候选计算历史相似模式下次日涨幅>=1%的概率",
    "rule: 以 'Reversal: ' 前缀发言，包含概率估计",
    "rule: 区分死猫跳 vs 可靠反弹"
  ]
}
```

**落地**：创建 `skills/reversal_analyst.skill.md`，注册到 agent 流水线，Bull↔Bear 辩论后路由到反弹分析师，再汇总到 Research Manager。

**验证**：海康威视 (002415) 从优化前 Hold → **Overweight 70%**，反弹分析师发挥了独立信号作用。

---

### 4.3 Pipeline 运行对比

```
优化前 (06-23 → 06-24):                  优化后 (06-24 → 06-25 预测):
─────────────────────────                 ────────────────────────
准确率: 60%                               结果待验证
STEP: 10 次                               预期 STEP 降低
  视觉板块 4/5 漏判                         视觉板块 0 Hold, 2 Overweight
  (海康 +8.3%, 大华 +2.6%, ...)            (海康 70%, 中科创达 Hold)
                                          reversal_analyst 已上线
```

---

## 五、架构演进时间线

```
v0.1: 手写 8 份 .skill.md
      ↓
v0.2: 引入 SkillOpt 管线 (collector/optimizer/applier/gate)
      ↓
v0.3: 新增 aggregate (去重) + select (top-k 评分)
      ↓
v0.4: 引入 EvoSkill 收敛检测 + 结构性发现 (evolve.py)
      ↓
v1.0: (当前) 9-agent 流水线 + SkillOpt + EvoSkill 双层自进化
      ┌──────────────────────────────────────┐
      │ Step 1-4:   SkillOpt 行级优化 (每日) │
      │ Step 5:     EvoSkill 结构性发现     │
      │            (收敛时自动触发)          │
      │ Discovery → 人工审核 → 新增 Agent   │
      │ 新 Agent 自动纳入 SkillOpt 管理      │
      └──────────────────────────────────────┘
```

---

## 六、关键文件索引

| 层级 | 文件 | 功能 |
|:--|:--|:--|
| SkillOpt | `opt/collector.py` | 回测信号采集 |
| SkillOpt | `opt/optimizer.py` | LLM 错误分析 → edits.json |
| SkillOpt | `opt/aggregate.py` | 合并去重相似编辑 |
| SkillOpt | `opt/select.py` | 四维评分挑选 top-k |
| SkillOpt | `opt/applier.py` | 写入 SKILLOPT-EDITABLE 区域 |
| SkillOpt | `opt/gate.py` | 新旧 accuracy 对比 |
| EvoSkill | `opt/evolve.py` | 收敛检测 + 结构性发现 |
| EvoSkill | `opt/output/discovery.json` | 发现提案 |
| Pipeline | `opt/run_pipeline.py` | 统一入口 + 自动收敛检测 |
| Skill | `skills/*.skill.md` | 9 份被优化的 skill |
| Agent | `graph/setup.py` | Agent 节点注册 |
| Agent | `graph/conditional_logic.py` | 辩论路由 |

---

## 七、总结

| | SkillOpt | EvoSkill | 本项目 |
|:--|:--|:--|:--|
| **做什么** | 精细调优已有规则 | 发现缺失的能力模块 | 两者结合 |
| **做多深** | 行级编辑 | 文件夹级创建 | 行级 + 架构级 |
| **何时触发** | 每轮 pipeline | SkillOpt 收敛时 | 每日 + 收敛检测 |
| **自主性** | 全自动 | 半自动 (人工审核) | 同左 |
| **产物** | 修改后的 skill.md | 全新 skill 文件夹 | 两者 |
| **防止退化** | Gate 二元判定 | Pareto 前沿 G | Gate + 人工审核 |

核心哲学：**SkillOpt 是每天的滴灌，EvoSkill 是平台的跃迁。先让模型在文本空间里做梯度下降，当梯度消失时，问 LLM 一个更深的问题——这个架构本身是不是缺了什么？**

---

*文档生成: 2026-06-25*
*项目: [DayTradeSelfOptAgent](https://github.com/Titanx/DayTradeSelfOptAgent)*
