"""AStockAgent 数据适配器连通性诊断"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from dataflows.akshare_adapter import (
    get_stock_realtime, get_stock_daily, get_financial_data,
    get_financial_indicators, get_market_sentiment, get_north_flow,
    get_sector_boards, get_latest_trade_date,
)

print("=" * 55)
print("  AStockAgent 适配器连通性诊断")
print("=" * 55)

SYMBOL = "600519"
trade_date = get_latest_trade_date()
print(f"\n📅 最近交易日: {trade_date}")
print(f"🔑 数据源策略: 东方财富 → 新浪 → 腾讯 → 同花顺\n")

tests = [
    ("实时行情", lambda: get_stock_realtime(SYMBOL),
     lambda r: r and r.get("name", "") or r.get("price", 0) > 0,
     "可获取个股价格 → LLM能拿到最新价"),
    ("日K线数据", lambda: get_stock_daily(SYMBOL, end_date=trade_date.replace("-", "")),
     lambda r: r is not None and not r.empty,
     "可获取历史K线 → 技术面分析有数据支抿"),
    ("财务指标(同花顺)", lambda: get_financial_indicators(SYMBOL),
     lambda r: r is not None and not r.empty,
     "可获取ROE/毛利等 → 基本面分析有数据支撑"),
    ("北向资金", lambda: get_north_flow(days=5),
     lambda r: r is not None and not r.empty,
     "可获取北向资金 → 资金面分析有数据支撑"),
    ("市场情绪", lambda: get_market_sentiment(),
     lambda r: r and r.get("up_count", 0) > 0,
     "可获取涨跌家数 → 情绪面分析有数据支撑"),
    ("行业板块(同花顺)", lambda: get_sector_boards(),
     lambda r: r is not None and not r.empty,
     "可获取板块排行 → 行业轮动分析有数据支撑"),
    ("财务三大表", lambda: get_financial_data(SYMBOL),
     lambda r: r and (r.get("balance") is not None or r.get("income") is not None),
     "可获取财报 → 深化基本面分析 (东方财富源,可能受限)"),
]

ok = fail = 0
for name, func, check, desc in tests:
    try:
        result = func()
        if check(result):
            detail = ""
            if isinstance(result, dict) and "price" in result:
                detail = f" → {result.get('name','')} 价格={result['price']}"
            elif hasattr(result, '__len__') and not isinstance(result, str):
                detail = f" → {len(result)}条记录"
            print(f"  ✅ {name}: {desc}{detail}")
            ok += 1
        else:
            print(f"  ⚠️  {name}: 数据为空 ({desc})")
            fail += 1
    except Exception as e:
        print(f"  ❌ {name}: {type(e).__name__}: {str(e)[:50]}")
        fail += 1

print(f"\n{'=' * 55}")
print(f"  通过: {ok}/{ok+fail}")
if ok >= 4:
    print("  ✅ 核心数据链路正常, 可以运行批量分析!")
elif ok >= 2:
    print("  ⚠️  部分接口可用, LLM仍可基于经验完成分析")
else:
    print("  ❌ 数据获取严重受限, 建议检查网络/防火墙")
print(f"{'=' * 55}")
