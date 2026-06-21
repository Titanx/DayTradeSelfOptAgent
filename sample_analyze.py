"""
单股分析示例 — 在本地跑一只股票验证全流程

用法:
  conda activate stocka
  set DEEPSEEK_API_KEY=sk-a1207783a1ea4547af8bb3fe20db6484
  python sample_analyze.py
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime

project_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(project_dir))

# ============================================================
# 配置
# ============================================================
SYMBOL = "600519"          # 股票代码
STOCK_NAME = "贵州茅台"     # 股票名称
SECTOR = "白酒"             # 板块
TRADE_DATE = get_latest_trade_date()

# ============================================================
# 1. 测试 AKShare 数据连通性
# ============================================================
print("=" * 60)
print(f"  AStockAgent 单股分析示例")
print(f"  目标: {STOCK_NAME} ({SYMBOL})")
print("=" * 60)

print("\n[1/4] 测试 AKShare 数据连通性...")
try:
    from dataflows.akshare_adapter import (
        get_stock_realtime,
        get_stock_daily,
        get_financial_data,
        get_market_sentiment,
        get_north_flow,
    )

    # 实时行情
    rt = get_stock_realtime(SYMBOL)
    if rt:
        print(f"  实时行情: {rt.get('name', '?')} 价格={rt.get('price', '?')} 涨幅={rt.get('change_pct', '?')}")
    else:
        print("  实时行情: 未获取到（非交易时段可能为空）")

    # 历史K线
    hist = get_stock_daily(SYMBOL, end_date=TRADE_DATE.replace("-", ""))
    if hist is not None and not hist.empty:
        print(f"  历史K线: 最近{len(hist)}天数据 OK")
    else:
        print("  历史K线: 未获取到")

    # 财务数据
    fin = get_financial_data(SYMBOL)
    if fin is not None and not fin.empty:
        print(f"  财务数据: {len(fin)}条 OK")
    else:
        print("  财务数据: 未获取到")

    # 市场情绪
    sent = get_market_sentiment()
    if sent:
        print(f"  市场情绪: 上涨{sent.get('up_count', '?')} 下跌{sent.get('down_count', '?')}")

    # 北向资金
    nf = get_north_flow(days=5)
    if nf is not None and not nf.empty:
        print(f"  北向资金: 最近{len(nf)}天数据 OK")

    print("  AKShare 数据连通性: OK")

except Exception as e:
    print(f"  AKShare 错误: {e}")
    print("  请确认: 1) akshare已安装  2) 网络可访问东方财富")

# ============================================================
# 2. 初始化 Agent
# ============================================================
print("\n[2/4] 初始化多Agent系统...")
from config.default_config import get_config
from graph.trading_graph import AStockTradingGraph
from dataflows.akshare_adapter import get_latest_trade_date

config = get_config()
agent = AStockTradingGraph(config=config, debug=True)
print("  Agent 初始化完成")

# ============================================================
# 3. 执行分析
# ============================================================
print(f"\n[3/4] 开始分析 {STOCK_NAME} ({SYMBOL})...")
print("  (多Agent辩论中，预计需要1-3分钟)")
print("-" * 60)

t0 = time.time()
result = agent.analyze(
    symbol=SYMBOL,
    trade_date=TRADE_DATE,
    stock_name=STOCK_NAME,
)
elapsed = time.time() - t0

print("-" * 60)
print(f"  分析完成，耗时 {elapsed:.1f} 秒")

# ============================================================
# 4. 输出结果
# ============================================================
print(f"\n[4/4] 分析结果")
print("=" * 60)

rating = result.get("rating", "Hold")
action = result.get("action", "Hold")
confidence = result.get("confidence", 0)
decision = result.get("decision", "")

print(f"  股票: {result.get('stock_name', STOCK_NAME)} ({SYMBOL})")
print(f"  日期: {result.get('trade_date', '?')}")
print(f"  评级: {rating}")
print(f"  动作: {action}")
print(f"  信心度: {confidence:.0%}")
print(f"\n  决策摘要:")
print(f"  {decision[:500]}")

# ============================================================
# 5. 保存结果到项目 results/ 文件夹
# ============================================================
results_dir = project_dir / "results" / SYMBOL
results_dir.mkdir(parents=True, exist_ok=True)

ts = datetime.now().strftime("%Y%m%d_%H%M%S")

# JSON
json_path = results_dir / f"{ts}_analysis.json"
with open(json_path, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print(f"\n  JSON: {json_path}")

# Thinking MD
md_path = results_dir / f"{ts}_thinking.md"
with open(md_path, "w", encoding="utf-8") as f:
    f.write(f"# {STOCK_NAME} ({SYMBOL}) 分析思考过程\n\n")
    f.write(f"**日期**: {result.get('trade_date', '?')}  \n")
    f.write(f"**板块**: {SECTOR}  \n")
    f.write(f"**评级**: {rating}  \n")
    f.write(f"**动作**: {action}  \n")
    f.write(f"**信心度**: {confidence:.0%}  \n\n")
    f.write("---\n\n")
    f.write("## 完整决策报告\n\n")
    f.write(decision)
print(f"  MD:   {md_path}")

print(f"\n{'=' * 60}")
print(f"  全流程验证完成!")
print(f"  如果看到真实数据（价格、涨跌幅等），说明AKShare正常工作")
print(f"  可以放心运行 batch_analyze.py 批量分析了")
print(f"{'=' * 60}")
