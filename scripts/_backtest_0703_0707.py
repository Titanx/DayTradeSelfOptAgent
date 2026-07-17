"""回测: 7/3预测 → 7/6买入 → 7/7卖出 (A股T+1 + 止损)
D+0预测 → D+1买入 → D+2卖出
  HIT  = 看多 + D+2日内最高 ≥ 买入价+1% → 止盈+1%
  STOP = 看多 + D+2日内最低 ≤ 买入价-3% → 止损-3%
  FLAT = 看多 + 未触发止盈/止损 → 收盘平仓
  MISS = FLAT中收盘<本(实亏)
  AVOID = 观望 + 未触发STEP
  STEP = 观望 + D+2涨≥1%
"""
import json, urllib.request, sys
from pathlib import Path
from collections import defaultdict

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))
RESULTS_DIR = PROJECT_DIR / "data" / "results"

# H8 修复：止盈止损参数读 config，避免硬编码（参考 batch_backtest.py 的 H2 修复）
from config.default_config import get_config as _get_cfg
_swing_cfg = _get_cfg().get("one_day_swing", {})
TARGET_GAIN_PCT = _swing_cfg.get("target_gain_pct", 1.0)   # 止盈线 +1%
STOP_LOSS_PCT = _swing_cfg.get("stop_loss_pct", 3.0)        # 止损线 -3%

STOCKS = [
    ("600438","通威股份","光伏"),("601012","隆基绿能","光伏"),("300274","阳光电源","光伏"),
    ("688599","天合光能","光伏"),("300751","迈为股份","光伏"),
    ("002202","金风科技","风电"),("601615","明阳智能","风电"),("603606","东方电缆","风电"),
    ("300850","新强联","风电"),("001289","龙源电力","风电"),
    ("002230","科大讯飞","AI"),("688256","寒武纪","AI"),("000977","浪潮信息","AI"),
    ("300308","中际旭创","AI"),("300033","同花顺","AI"),
    ("300750","宁德时代","储能"),("300014","亿纬锂能","储能"),("002074","国轩高科","储能"),
    ("002460","赣锋锂业","储能"),("601727","上海电气","储能"),
    ("002415","海康威视","视觉"),("002236","大华股份","视觉"),("002920","德赛西威","视觉"),
    ("300496","中科创达","视觉"),("603501","韦尔股份","视觉"),
]

D0_DATE = "2026-07-03"
D1_DATE = "2026-07-06"
D2_DATE = "2026-07-07"


def get_kline_data(code):
    """返回 D0收, D1开, D2高, D2低, D2收"""
    code = code[2:] if len(code) > 6 else code
    sid = ("sh" if code.startswith(("6","9")) else "sz") + code
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sid},day,,,10,qfq"
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        klines = json.loads(resp.read().decode("utf-8"))["data"][sid]
        klines = klines.get("qfqday") or klines.get("day",[])
        d0c=d1o=d2h=d2l=d2c=None
        for k in klines:
            if k[0]==D0_DATE: d0c=float(k[2])
            if k[0]==D1_DATE: d1o=float(k[1])
            if k[0]==D2_DATE: d2h=float(k[3]); d2l=float(k[4]); d2c=float(k[2])
        return d0c,d1o,d2h,d2l,d2c
    except Exception:
        return None,None,None,None,None


def load_prediction(code):
    for f in RESULTS_DIR.glob(f"{code}_{D0_DATE}_*analysis.cache.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        return {"symbol":d.get("symbol",code),"stock_name":d.get("stock_name",""),
                "rating":d.get("rating","?"),"confidence":d.get("confidence",0)}
    return None


def pct_str(v): return "{:+.2f}%".format(v)


print("=" * 70)
print(f"  25股回测 (T+1 + 止损)")
print(f"  止盈≥+1% | 止损≤-3% | 否则收盘平仓")
print("=" * 70)

hit=avoid=miss=step=flat=stop=nodata=0
records=[]

for code,name,sector in STOCKS:
    pred=load_prediction(code)
    d0c,d1o,d2h,d2l,d2c=get_kline_data(code)
    if pred is None or d0c is None:
        nodata+=1; continue
    is_bull = pred["rating"].lower() in ("buy","overweight")
    # H8 修复：止盈止损参数读 config；STEP 基准改用 d1o（买入价）与 collector.py 对齐
    hit_p = d1o*(1+TARGET_GAIN_PCT/100.0); stop_p = d1o*(1-STOP_LOSS_PCT/100.0)
    step_trigger = (d2h/d1o-1)*100 >= TARGET_GAIN_PCT
    close_profit = (d2c/d1o-1)*100

    if is_bull and d2h >= hit_p:
        exit_price=hit_p; result="HIT"; hit+=1
    elif is_bull and d2l <= stop_p:
        exit_price=stop_p; result="STOP"; stop+=1
    elif is_bull:
        exit_price=d2c; result="FLAT"; flat+=1
    elif step_trigger:
        result="STEP"; step+=1; exit_price=None
    else:
        result="AVOID"; avoid+=1; exit_price=None

    records.append({"code":code,"name":name,"sector":sector,
        "rating":pred["rating"],"conf":pred["confidence"],"is_bull":is_bull,
        "d0c":d0c,"d1o":d1o,"d2h":d2h,"d2l":d2l,"d2c":d2c,
        "exit":exit_price,"close_profit":close_profit,"result":result})

total=hit+avoid+flat+stop+step
bull_total=hit+stop+flat
print(f"\n{'='*70}")
print(f"  回测结果")
print(f"{'='*70}")
print(f"  有效:{total}/{len(STOCKS)}")
print(f"  🎯 HIT  (止盈+1%):    {hit}")
print(f"  🛑 STOP (止损-3%):    {stop}")
print(f"  ⚪ FLAT (收盘平仓):   {flat}")
print(f"  ✅ AVOID (正确回避):  {avoid}")
print(f"  👣 STEP (踏空):       {step}")
if bull_total>0:
    pnl_sum = hit*(0.01) + stop*(-0.03)
    for r in records:
        if r["result"]=="FLAT": pnl_sum += r["close_profit"]/100
    print(f"  💰 看多信号平均盈亏: {pnl_sum/bull_total*100:+.2f}%")
if total>0:
    print(f"  📈 准确率(HIT+AVOID): {(hit+avoid)/total*100:.1f}%")

print(f"\n{'─'*70}")
print(f"  详细表")
print(f"{'─'*70}")
print(f"  {'代码':<8} {'名称':<8} {'评级':<12} {'买入':<8} {'最高':<8} {'最低':<8} {'收盘':<8} {'盈亏%':<7} {'结果'}")
for r in records:
    if r.get("nodata"): continue
    m="🟢" if r["result"]=="HIT" else ("🛑" if r["result"]=="STOP" else "🔴" if r["result"]=="FLAT" and r["close_profit"]<0 else "⚪" if r["result"]=="FLAT" else "👣" if r["result"]=="STEP" else "⚪")
    print(f"  {m} {r['code']:<6} {r['name']:<8} {r['rating']:<12} {r.get('d1o',0):>8.2f} {r.get('d2h',0):>8.2f} {r.get('d2l',0):>8.2f} {r.get('d2c',0):>8.2f} {pct_str(r.get('close_profit',0) or 0):>7} {r['result']}")

# detail for bull signals
bulls=[r for r in records if r.get("is_bull")]
if bulls:
    print(f"\n{'─'*70}")
    print(f"  看多信号详情")
    for r in bulls:
        print(f"  {r['result']} {r['code']} {r['name']}({r['sector']}) {r['rating']} {r['conf']*100:.0f}% | 买{r['d1o']:.2f} 高{r['d2h']:.2f} 低{r['d2l']:.2f} 收{r['d2c']:.2f} | 盈亏{pct_str(r['close_profit'])}")
print()
