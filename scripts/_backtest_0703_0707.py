"""回测: 7/2预测 → 7/3买入 → 7/6卖出 (A股T+1真实约束)
时间线:
  D+0 (7/2周四) 收盘 → Agent预测 → 用户看到信号
  D+1 (7/3周五) 开盘买入 ← 真实买入成本 = 7/3开盘价
  D+2 (7/6周一) 卖出     ← 7/6日内最高价可实现止盈

命中判断:
  HIT  = 看多 + D+2日内最高 ≥ 买入成本 + 1%
  MISS = 看多 + D+2日内最高 < 买入成本 + 1%
  AVOID = 观望 + 不满足STEP条件
  STEP = 观望 + D+2日内最高 ≥ D+0收盘价 + 1%
"""
import json
import urllib.request
import sys
from pathlib import Path
from collections import defaultdict

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))
RESULTS_DIR = PROJECT_DIR / "data" / "results"

STOCKS = [
    ("600438", "通威股份", "光伏"), ("601012", "隆基绿能", "光伏"), ("300274", "阳光电源", "光伏"),
    ("688599", "天合光能", "光伏"), ("300751", "迈为股份", "光伏"),
    ("002202", "金风科技", "风电"), ("601615", "明阳智能", "风电"), ("603606", "东方电缆", "风电"),
    ("300850", "新强联", "风电"), ("001289", "龙源电力", "风电"),
    ("002230", "科大讯飞", "AI"), ("688256", "寒武纪", "AI"), ("000977", "浪潮信息", "AI"),
    ("300308", "中际旭创", "AI"), ("300033", "同花顺", "AI"),
    ("300750", "宁德时代", "储能"), ("300014", "亿纬锂能", "储能"), ("002074", "国轩高科", "储能"),
    ("002460", "赣锋锂业", "储能"), ("601727", "上海电气", "储能"),
    ("002415", "海康威视", "视觉"), ("002236", "大华股份", "视觉"), ("002920", "德赛西威", "视觉"),
    ("300496", "中科创达", "视觉"), ("603501", "韦尔股份", "视觉"),
]

D0_DATE = "2026-07-03"   # 预测日(周五收盘)
D1_DATE = "2026-07-06"   # 买入日(周一开盘)
D2_DATE = "2026-07-07"   # 卖出日(周二)


def get_kline_data(code):
    """返回 D0收盘价, D1开盘价, D2日内最高价"""
    code = code[2:] if len(code) > 6 else code
    if code.startswith(("6", "9")):
        sid = "sh" + code
    else:
        sid = "sz" + code
    url = (
        "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        "?param={sid},day,,,10,qfq".format(sid=sid)
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))["data"][sid]
        klines = data.get("qfqday") or data.get("day", [])
        d0_close, d1_open, d2_high = None, None, None
        for k in klines:
            if k[0] == D0_DATE:
                d0_close = float(k[2])
            if k[0] == D1_DATE:
                d1_open = float(k[1])
            if k[0] == D2_DATE:
                d2_high = float(k[3])
        return d0_close, d1_open, d2_high
    except Exception as e:
        return None, None, None


def load_prediction(code):
    for f in RESULTS_DIR.glob(f"{code}_{D0_DATE}_*analysis.cache.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        return {
            "symbol": d.get("symbol", code),
            "stock_name": d.get("stock_name", ""),
            "rating": d.get("rating", "?"),
            "confidence": d.get("confidence", 0),
            "macro_chars": len(d.get("reports", {}).get("global_macro", "")),
        }
    return None


def pct_str(v):
    return "{:+.2f}%".format(v)


print("=" * 70)
print(f"  25股回测 (A股T+1真实约束)")
print(f"  D0={D0_DATE}预测 → D1={D1_DATE}买入 → D2={D2_DATE}卖出")
print(f"  策略: D+2日内最高 ≥ 买入价+1% 即止盈")
print("=" * 70)

hit = avoid = miss = step = nodata = 0
records = []

for code, name, sector in STOCKS:
    pred = load_prediction(code)
    d0_close, d1_open, d2_high = get_kline_data(code)

    if pred is None or d0_close is None or d1_open is None or d2_high is None:
        nodata += 1
        records.append({"code": code, "name": name, "sector": sector, "nodata": True})
        continue

    is_bull = pred["rating"].lower() in ("buy", "overweight")
    cost = d1_open
    exit_high = d2_high

    # 止盈条件: 日内最高 ≥ 买入成本 + 1%
    can_exit = (exit_high / cost - 1) * 100 >= 1.0
    # 踏板: 观望的股票涨了≥1%
    step_trigger = (exit_high / d0_close - 1) * 100 >= 1.0

    if is_bull and can_exit:
        result = "HIT"
        hit += 1
    elif is_bull:
        result = "MISS"
        miss += 1
    elif step_trigger:
        result = "STEP"
        step += 1
    else:
        result = "AVOID"
        avoid += 1

    buy_pct = (d2_high / d1_open - 1) * 100
    close_pct = (d2_high / d0_close - 1) * 100

    records.append({
        "code": code, "name": name, "sector": sector,
        "rating": pred["rating"], "conf": pred["confidence"],
        "is_bull": is_bull,
        "d0_close": d0_close, "d1_open": d1_open, "d2_high": d2_high,
        "cost": cost, "exit": exit_high,
        "buy_chg": buy_pct, "close_chg": close_pct,
        "result": result
    })

total = hit + avoid + miss + step
print(f"\n{'=' * 70}")
print(f"  回测结果汇总")
print(f"{'=' * 70}")
print(f"  📊 有效: {total}/{len(STOCKS)} (缺数据: {nodata})")
print(f"  🎯 HIT   (看多 → D+2止盈成功):  {hit}")
print(f"  ✅ AVOID (观望 → D+2未触发止盈): {avoid}")
print(f"  ❌ MISS  (看多 → D+2止盈失败):    {miss}")
print(f"  👣 STEP  (观望 → D+2涨≥1%踏空):  {step}")
if total > 0:
    print(f"  📈 准确率: {(hit+avoid)/total*100:.1f}%")
if hit + miss > 0:
    print(f"  🎯 Buy命中率: {hit}/{hit+miss} = {hit/(hit+miss)*100:.1f}%")
up_stocks = hit + step
if up_stocks > 0:
    print(f"  👣 踏空率: {step}/{up_stocks} = {step/up_stocks*100:.0f}%")

# By sector
print(f"\n{'─' * 70}")
print(f"  板块表现")
print(f"{'─' * 70}")
by_sector = defaultdict(list)
for r in records:
    if not r.get("nodata"):
        by_sector[r["sector"]].append(r)

for sector in ["光伏", "风电", "AI", "储能", "视觉"]:
    rs = by_sector.get(sector, [])
    s_hit = sum(1 for r in rs if r["result"] == "HIT")
    s_avoid = sum(1 for r in rs if r["result"] == "AVOID")
    s_miss = sum(1 for r in rs if r["result"] == "MISS")
    s_step = sum(1 for r in rs if r["result"] == "STEP")
    s_acc = (s_hit + s_avoid) / len(rs) * 100 if rs else 0
    s_bulls = sum(1 for r in rs if r["is_bull"])
    emoji = "🔥" if s_hit > 0 else ("✅" if s_miss == 0 and s_bulls == 0 else "⚠️")
    print(f"  {emoji} {sector}: 准确率{s_acc:.0f}% | HIT={s_hit} AVOID={s_avoid} MISS={s_miss} STEP={s_step} | 看多{s_bulls}只")

# Detail table
print(f"\n{'=' * 70}")
print(f"  详细回测表 (D0={D0_DATE}预测 → D1={D1_DATE}买入 → D2={D2_DATE}卖出)")
print(f"{'=' * 70}")
print(f"  {'代码':<8} {'名称':<8} {'板块':<4} {'评级':<12} {'信%':<5} {'买入':<7} {'D2最高':<7} {'买→顶%':<7} {'预测:':<8} {'结果':<8}")
print(f"  {'─'*8} {'─'*8} {'─'*4} {'─'*12} {'─'*5} {'─'*7} {'─'*7} {'─'*7} {'─'*8} {'─'*8}")

for r in records:
    if r.get("nodata"):
        continue
    if r["is_bull"]:
        marker = "🟢" if r["result"] == "HIT" else "🔴"
    elif r["result"] == "STEP":
        marker = "👣"
    else:
        marker = "⚪"
    rat = r["rating"][:12]
    name = r["name"][:8]
    print(f"  {marker} {r['code']:<6} {name:<8} {r['sector']:<4} {rat:<12} {r['conf']*100:>3.0f}% {r['cost']:>7.2f} {r['exit']:>7.2f} {pct_str(r['buy_chg']):>7} {pct_str(r['close_chg']):>7} {r['result']:<8}")

# Buy signal detail
bulls = [r for r in records if not r.get("nodata") and r["is_bull"]]
if bulls:
    print(f"\n{'─' * 70}")
    print(f"  看多信号详情 (D1={D1_DATE}买入 → D2={D2_DATE}卖出)")
    print(f"{'─' * 70}")
    for r in bulls:
        cost_pct = pct_str((r["d2_high"] / r["cost"] - 1) * 100)
        d0_pct = pct_str((r["d2_high"] / r["d0_close"] - 1) * 100)
        print(f"  {r['result']} {r['code']} {r['name']} ({r['sector']}) → {r['rating']} {r['conf']*100:.0f}% | 成本{r['cost']:.2f} | D2最高{r['exit']:.2f} | 买→顶={cost_pct} | D0→顶={d0_pct}")

# STEP detail
steps = [r for r in records if not r.get("nodata") and r["result"] == "STEP"]
if steps:
    print(f"\n{'─' * 70}")
    print(f"  踏空明细")
    print(f"{'─' * 70}")
    for r in steps:
        print(f"  👣 {r['code']} {r['name']} ({r['sector']}) → D2最高 / D0收盘 = {pct_str((r['d2_high']/r['d0_close']-1)*100)}")

print()
