"""
10支股票测试 — 验证缓存机制和结果是否正常

每个赛道取前 2 支，共 10 支。
观察点:
  1. 公共数据缓存命中（market_cache/ 目录）
  2. 个股舆情缓存命中（opinion_cache/ 目录）
  3. 结果是否正确产出 JSON + MD
"""
import os
import sys
import time
import logging
from pathlib import Path
from datetime import datetime

project_dir = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_dir))

from config.default_config import get_config
from graph.trading_graph import AStockTradingGraph
from dataflows.akshare_adapter import get_latest_trade_date
from dataflows.market_cache import MarketDataCache

# 日志级别设高，看清缓存命中
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)-5s %(message)s",
)

TEST_STOCKS = [
    ("600438", "通威股份", "光伏"),
    ("601012", "隆基绿能", "光伏"),
    ("002202", "金风科技", "风电"),
    ("601615", "明阳智能", "风电"),
    ("002230", "科大讯飞", "AI"),
    ("688256", "寒武纪",   "AI"),
    ("300750", "宁德时代", "储能"),
    ("300014", "亿纬锂能", "储能"),
    ("002415", "海康威视", "视觉"),
    ("002236", "大华股份", "视觉"),
]

TRADE_DATE = get_latest_trade_date()
CACHE = MarketDataCache.get_instance()
CACHE.set_trade_date(TRADE_DATE)

print("=" * 70)
print(f"  🔬 10支股票测试 — 缓存验证")
print(f"  📅 交易日: {TRADE_DATE}")
print(f"  📂 项目根目录: {project_dir}")
print("=" * 70)

# ———— 预加载公共数据 ————
print("\n📦 [Phase 0] 预加载公共数据到缓存...")
all_symbols = [s[0] for s in TEST_STOCKS]
preload_status = CACHE.preload(symbols=all_symbols)
for method, status in preload_status.items():
    print(f"    {status} {method}")

print(f"\n📂 缓存目录:")
print(f"    公共数据: {CACHE.cache_dir}")
print(f"    个股舆情: {CACHE.opinion_cache_dir}")

# ———— 初始化 Agent ————
print("\n🤖 [Phase 1] 初始化 AStockAgent...")
config = get_config()
config["debug"] = True
config["max_debate_rounds"] = 1
config["max_risk_discuss_rounds"] = 1
config["enable_opinion_monitor"] = True
agent = AStockTradingGraph(config=config, debug=True)
print("    ✅ Agent 就绪")

# ———— 逐支分析 ————
results = []
total_start = time.time()

for i, (code, name, sector) in enumerate(TEST_STOCKS, 1):
    print(f"\n{'─' * 70}")
    print(f"[{i:2d}/10] {name} ({code}) — {sector}")
    print(f"{'─' * 70}")

    t0 = time.time()
    try:
        result = agent.analyze(code, TRADE_DATE, name)
        elapsed = time.time() - t0

        rating = result.get("rating", "?")
        action = result.get("action", "?")
        conf = result.get("confidence", 0)

        emoji = {"Buy": "🟢", "Overweight": "🟡", "Hold": "⚪",
                 "Underweight": "🟠", "Sell": "🔴"}.get(rating, "❓")

        print(f"    {emoji} 评级={rating} 动作={action} 信心度={conf:.0%} 耗时={elapsed:.0f}s")

        result["sector"] = sector
        results.append(result)

    except Exception as e:
        elapsed = time.time() - t0
        print(f"    ❌ 失败: {e} (耗时={elapsed:.0f}s)")
        results.append({
            "symbol": code, "stock_name": name, "sector": sector,
            "rating": "Error", "error": str(e),
        })

    if i < len(TEST_STOCKS):
        time.sleep(1)

# ———— 汇总 ————
total_time = time.time() - total_start
success = [r for r in results if r.get("rating") not in ("Error", "?")]
errors = [r for r in results if r.get("rating") in ("Error", "?")]

print(f"\n{'=' * 70}")
print(f"  📊 测试完成!")
print(f"  ✅ 成功: {len(success)}/10 | ❌ 失败: {len(errors)}/10")
print(f"  ⏱️  总耗时: {total_time/60:.1f} 分钟")
print(f"{'=' * 70}")

# ———— 按赛道展示 ————
print(f"\n📋 各赛道结果:")
for sector_name in ["光伏", "风电", "AI", "储能", "视觉"]:
    sr = [r for r in results if r.get("sector") == sector_name]
    for r in sr:
        rating = r.get("rating", "?")
        action = r.get("action", "?")
        conf = r.get("confidence", 0)
        emoji = {"Buy": "🟢", "Overweight": "🟡", "Hold": "⚪",
                 "Underweight": "🟠", "Sell": "🔴", "Error": "❌"}.get(rating, "❓")
        name = r.get("stock_name", r.get("symbol", "?"))
        print(f"    {sector_name:4s} {emoji} {name:6s} {rating:12s} {action:5s} {conf:.0%}")

# ———— 检查缓存文件 ————
print(f"\n📂 缓存文件清单:")
market_files = sorted(CACHE.cache_dir.glob("*.md"))
opinion_files = sorted(CACHE.opinion_cache_dir.glob("*.md"))

print(f"  公共数据缓存 ({len(market_files)} 个文件):")
for f in market_files:
    print(f"    📦 {f.name}")

print(f"\n  个股舆情缓存 ({len(opinion_files)} 个文件):")
for f in opinion_files:
    print(f"    💬 {f.name}")

# ———— 查看第一个结果的内容摘要 ————
if results and results[0].get("decision"):
    print(f"\n📝 样本决策摘要 ({results[0].get('stock_name','')}):")
    decision = results[0].get("decision", "")
    import re
    summary_match = re.search(r'\*\*Executive Summary\*\*:(.*?)(?:\*\*|\Z)', decision, re.DOTALL)
    if summary_match:
        print(f"    {summary_match.group(1).strip()[:200]}")

print(f"\n✅ 测试结束 — 请检查上方缓存命中日志!")
