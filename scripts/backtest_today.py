"""0622预测 vs 0623实盘 — 25股一日游回测（一次性脚本）"""
# 注意: 本脚本使用 close-to-close 基准（d0_close → d1_close），与 collector.py 的
# d1_open 基准不可直接对比。为保持历史回测可复现性，不修改 HIT 基准。
import json, urllib.request, time
from pathlib import Path

# 股票池：从 stock_universe 统一来源取前 25 只（5 板块 × 5 只）
from scripts.stock_universe import STOCK_UNIVERSE
_STOCKS_FULL = list(STOCK_UNIVERSE)[:25]
STOCKS = []
for code, name, sector in _STOCKS_FULL:
    prefix = "sh" if code.startswith(("6", "9")) else "sz"
    STOCKS.append((f"{prefix}{code}", name, sector))

RESULTS_DIR = Path(__file__).parent.parent / "data" / "results"

def get_prediction(code):
    f = RESULTS_DIR / f"{code}_2026-06-22_analysis.cache.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text(encoding="utf-8"))
    return d.get("rating","?"), d.get("confidence",0)

def get_kline(sid):
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sid},day,,,3,qfq"
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    resp = urllib.request.urlopen(req, timeout=10)
    klines = json.loads(resp.read().decode("utf-8"))["data"][sid]["qfqday"]
    d0 = d1 = None
    for k in klines:
        if k[0] == "2026-06-22":
            d0 = float(k[2])
        if k[0] == "2026-06-23":
            d1 = {"open":float(k[1]),"close":float(k[2]),"high":float(k[3]),"low":float(k[4])}
    return d0, d1

def color_pct(pct):
    s = f"{pct:+.2f}%"
    if pct >= 3: return f"🔥{s}"
    if pct >= 1: return f"📈{s}"
    if pct >= 0: return f"➖{s}"
    return f"📉{s}"


def main():
    print("=" * 75)
    print("  一日游回测: 0622预测 → 0623收盘")
    print("=" * 75)
    print(f"{'代码':<8}{'名称':<8}{'板块':<6}{'预测':<14}{'信心':<6}{'开盘':<8}{'收盘':<8}{'涨跌':<12}{'开盘买':<8}{'结果'}")
    print("-" * 75)

    hit = avoid = miss = step_on = 0
    results = []

    for sid, name, sector in STOCKS:
        code = sid[2:]
        pred = get_prediction(code)
        if not pred:
            continue
        rating, conf = pred
        try:
            d0, d1 = get_kline(sid)
            time.sleep(0.1)
        except Exception as e:
            continue
        if d0 is None or d1 is None:
            continue

        close_pct = (d1["close"]/d0 - 1)*100
        open_pct = (d1["close"]/d1["open"] - 1)*100
        net_pct = open_pct - 0.11

        should_buy = rating in ("Buy","Overweight")
        actually_up = close_pct >= 1.0

        if should_buy and actually_up: verdict = "HIT 命中"
        elif should_buy: verdict = "MISS 误判"
        elif actually_up: verdict = "STEP 踏空"
        else: verdict = "AVOID 回避"

        if should_buy and actually_up: hit += 1
        elif should_buy: miss += 1
        elif actually_up: step_on += 1
        else: avoid += 1

        results.append((code, name, sector, rating, conf, d0, d1["open"], d1["close"], close_pct, open_pct, net_pct, verdict))

    for r in results:
        code, name, sector, rating, conf, d0, dop, dclose, cpct, opct, net, verdict = r
        print(f"{code:<8}{name:<8}{sector:<6}{rating:<14}{conf:.0%}{'':<2}{dop:<8.2f}{dclose:<8.2f}{color_pct(cpct):<16}{color_pct(opct):<8}{verdict}")

    total = hit + avoid + miss + step_on
    print("\n" + "=" * 75)
    print("  汇总")
    print("=" * 75)
    print(f"  总: {total}笔  |  HIT: {hit}  |  AVOID: {avoid}  |  MISS: {miss}  |  STEP: {step_on}")
    print(f"  准确率: {(hit+avoid)/total*100:.0f}% ({hit+avoid}/{total})")
    if hit+miss > 0:
        print(f"  Buy信号准确率: {hit}/{hit+miss} = {hit/(hit+miss)*100:.0f}%")
    print(f"  踏空率: {step_on/total*100:.0f}%")
    print(f"  误判率: {miss/total*100:.0f}%")


if __name__ == "__main__":
    main()
