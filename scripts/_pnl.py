"""7/3轮次交易盈亏 + D2 -3%止损"""
import json, re
from pathlib import Path

RESULTS_DIR = Path(r"c:\Users\44263\Documents\xhl\skills\量化交易\AStockAgent\data\results")
D0 = "2026-07-03"
TOTAL = 1_000_000

# (code, name, sector, d1_open, d2_high, d2_low, d2_close)
BULLS = [
    ("002202", "金风科技", "风电", 24.73, 23.70, 22.03, 22.19),
    ("603606", "东方电缆", "风电", 43.32, 42.23, 40.30, 40.56),
    ("000977", "浪潮信息", "AI",   66.40, 73.23, 68.70, 71.06),
    ("300308", "中际旭创", "AI", 1136.54, 1138.20, 1089.00, 1121.90),
    ("300033", "同花顺", "AI",   250.50, 243.00, 235.01, 236.20),
    ("002460", "赣锋锂业", "储能", 63.19, 64.17, 61.25, 61.44),
    ("002415", "海康威视", "视觉", 34.14, 34.82, 33.42, 33.86),
    ("002236", "大华股份", "视觉", 16.73, 16.82, 16.29, 16.43),
]

def get_position(f):
    d = json.loads(f.read_text(encoding="utf-8"))
    m = re.search(r'"position_size"\s*:\s*([\d.]+)', d.get("decision",""))
    if m: return float(m.group(1))
    a = d.get("action","")
    if "Buy" in a: return 0.20
    if "Overweight" in a: return 0.15
    return 0.15

print("=" * 80)
print("  7/3→7/6→7/7  真实交易盈亏 + D2止损 (100万总仓)")
print("  规则: D2高≥+1%→止盈+1% | D2低≤-3%→止损-3% | 否则→收盘平仓")
print("=" * 80)
h = f"  {'代码':<8} {'名称':<8} {'仓位':<6} {'买入':<8} {'卖出':<8} {'盈亏':<12} {'盈%':<7} {'方式'}"
print(h)
print(f"  {'─'*8} {'─'*8} {'─'*6} {'─'*8} {'─'*8} {'─'*12} {'─'*7} {'─'*20}")

# 归一化仓位
raw_pos = []
for code, name, sec, d1_open, d2_high, d2_low, d2_close in BULLS:
    for f in RESULTS_DIR.glob(f"{code}_{D0}_*analysis.cache.json"):
        raw_pos.append(get_position(f))
        break
scale = 1.0 / sum(raw_pos) if sum(raw_pos) > 1 else 1.0

total_pnl = total_cost = 0
for i, (code, name, sec, d1_open, d2_high, d2_low, d2_close) in enumerate(BULLS):
    pos = raw_pos[i] * scale

    hit_price = round(d1_open * 1.01, 2)   # +1% 止盈价
    stop_price = round(d1_open * 0.97, 2)   # -3% 止损价

    if d2_high >= hit_price:
        exit_price = hit_price
        exit_type = "止盈+1%"
    elif d2_low <= stop_price:
        exit_price = stop_price
        exit_type = "止损-3%"
    else:
        exit_price = d2_close
        exit_type = "收盘平仓"

    shares = int((TOTAL * pos) / d1_open / 100) * 100
    cost = round(shares * d1_open, 0)
    revenue = round(shares * exit_price, 0)
    pnl = revenue - cost
    pnl_pct = (exit_price / d1_open - 1) * 100

    total_pnl += pnl
    total_cost += cost

    mark = "🟢" if pnl > 0 else "🔴"
    print(f"  {mark} {code:<6} {name:<8} {pos*100:>4.0f}%  {d1_open:>8.2f} {exit_price:>8.2f} {pnl:>+12,.0f} {pnl_pct:>+6.2f}% {exit_type}")

print(f"  {'─'*8} {'─'*8} {'─'*6} {'─'*8} {'─'*8} {'─'*12} {'─'*7} {'─'*20}")
print(f"  总投入: {total_cost:>12,.0f} 元")
print(f"  总盈亏: {total_pnl:>+12,.0f} 元   总收益率: {total_pnl/TOTAL*100:+.2f}%")
print(f"  未使用: {TOTAL - total_cost:>12,.0f} 元   仓位: {total_cost/TOTAL*100:.0f}%")
print()

# 对比无止损
print("─" * 60)
print("  止损效果对比")
print("─" * 60)
print(f"  {'代码':<8} {'无止损':<10} {'有止损':<10} {'改善':<10}")
for i, (code, name, sec, d1_open, d2_high, d2_low, d2_close) in enumerate(BULLS):
    no_stop = (d2_close / d1_open - 1) * 100
    hit_p = round(d1_open * 1.01, 2)
    stop_p = round(d1_open * 0.97, 2)
    if d2_high >= hit_p:
        with_stop = 1.0
    elif d2_low <= stop_p:
        with_stop = -3.0
    else:
        with_stop = (d2_close / d1_open - 1) * 100
    diff = with_stop - no_stop
    mark = "✅" if diff > 0 else ("➡️" if diff == 0 else "🔻")
    print(f"  {mark} {code:<6} {no_stop:>+7.2f}%   {with_stop:>+7.2f}%   {diff:>+7.2f}pp")
print()
