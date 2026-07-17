# data/ 目录说明

```
data/
├── results/            # 📊 当前分析结果 (温度0.1版本)
├── results_temp03/     # 📦 归档: 温度0.3版本的历史结果 (用于A/B对比)
│
├── agent_cache/        # 🧠 LLM 辩论轨迹 (按symbol子目录)
├── opinion_cache/      # 💬 舆论数据缓存 (雪球/微博/新闻)
├── stock_cache/        # 📈 个股数据缓存 (行情/K线/财务)
├── market_cache/       # 📉 公共数据缓存 (情绪/板块/北向)
│
├── batch_results/      # 📋 batchanalyze.py 批量输出
├── checkpoints/        # ⏸️ LangGraph 检查点 (待用)
├── data_cache/         # 🗄️ 通用数据缓存
└── memory/             # 🧾 交易记忆系统 (模拟持仓/收益记录)
```

---

## 文件夹详解

### results/
当前运行结果，格式: `{symbol}_{date}_analysis.{md,cache.json}`
- `.md` — 人类可读的完整分析报告
- `.cache.json` — 程序可解析的评级/信心度/摘要
- 被回测脚本 `scripts/backtest_*.py` 直接读取

### results_temp03/
温度 0.3 时代的完整归档。当需要对比 temperature 调整前后的评级差异时，与 `results/` 做逐股 diff。

### agent_cache/
每次分析的完整 LLM 对话流, 格式: `{date}_agent_trace.{md,cache.json}`
- 记录所有 Agent 的 prompt + 输出, 可用于调试 prompt 效果

### opinion_cache/
舆论相关数据，按 symbol 子目录组织:
- `{date}_get_opinion_report.{md,cache.json}` — 聚合情绪报告
- `{date}_get_xueqiu_hot_posts.{md,cache.json}` — 雪球热帖

### stock_cache/
个股行情数据，按 symbol 子目录:
- `{date}_get_stock_price_data.{md,cache.json}` — 日线K线
- `{date}_get_stock_realtime_quote.{md,cache.json}` — 实时行情
- `{date}_get_stock_financials.{md,cache.json}` — 财务指标
- `price_daily_{date}.{md,cache.json}` — 30天日线

### market_cache/
公共市场数据，按日期:
- `{date}_get_market_sentiment.{md,cache.json}` — 市场情绪
- `{date}_get_sector_boards.{md,cache.json}` — 板块排行
- `{date}_get_north_flow.{md,cache.json}` — 北向资金

### memory/
交易记忆: 模拟持仓记录、每笔交易盈亏、收益日历

---

## 缓存策略

| 数据类型 | 跨会话恢复 | 历史数据 |
|----------|:--:|:--:|
| 市场情绪/板块排行 | ✅ preload() | ✅ 30天 |
| 北向资金 | ✅ preload() | ✅ 逐日累积 |
| 个股日线 | ✅ preload() | ✅ 30天 |
| 个股实时行情 | ✅ preload() | ❌ 仅当天 |
| 个股财务指标 | ✅ preload() | ❌ 仅当天 |
| 舆论情绪报告 | ✅ preload() | ❌ 仅当天 |
| LLM 辩论轨迹 | ❌ 每次新生成 | ❌ 每次覆盖 |

所有缓存 `.cache.json` 格式一致: `{data, timestamp, ...}` 便于统一解析。
