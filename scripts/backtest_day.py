"""一日游回测: Day0(0622分析) → Day1(0623实盘)"""
# TODO: STEP 基准未统一为 d1o（round-9 未修）
# 该脚本为针对 2026-06-22→0623 的一次性历史回测（日期与 PREDICTIONS 均硬编码），
# 修改 STEP 基准会破坏历史回测可复现性，故按 round-9 保守策略仅标注，不改逻辑。
# 注意: 本脚本使用 close-to-close 基准（d0_close → d1_close），与 collector.py 的
# d1_open 基准不可直接对比。为保持历史回测可复现性，不修改 HIT 基准。
import urllib.request, json

STOCKS = [
    ("sz300750", "宁德时代"),
    ("sh600438", "通威股份"),
    ("sz300033", "同花顺"),
    ("sz002202", "金风科技"),
    ("sz002415", "海康威视"),
]

# 预测结果 (从测试输出)
PREDICTIONS = {
    "300750": {"rating": "Hold", "confidence": 0.35, "action": "Hold"},
    "600438": {"rating": "Hold", "confidence": 0.35, "action": "Hold"},
    "300033": {"rating": "Overweight", "confidence": 0.72, "action": "Buy", "logic": "放量洗盘+证券板块补涨"},
    "002202": {"rating": "Hold", "confidence": 0.35, "action": "Hold"},
    "002415": {"rating": "Hold", "confidence": 0.25, "action": "Hold"},
}


def main():
    print("=" * 72)
    print("  一日游策略回测: Day0(0622收盘分析) → Day1(0623实盘)")
    print("=" * 72)

    for sid, name in STOCKS:
        pure_code = sid[2:]
        try:
            url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sid},day,,,5,qfq"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read().decode("utf-8"))
            klines = data["data"][sid]["qfqday"]

            d0 = d1 = None
            for k in klines:
                if k[0] == "2026-06-22":
                    d0 = float(k[2])
                if k[0] == "2026-06-23":
                    d1 = {"open": float(k[1]), "close": float(k[2]),
                          "high": float(k[3]), "low": float(k[4])}

            if not d1:
                print(f"\n  {pure_code} {name}: ⚠️ 0623数据未出")
                continue

            close_pct = (d1["close"] / d0 - 1) * 100
            open_pct = (d1["close"] / d1["open"] - 1) * 100
            # 实际收益 = 开盘买入 → 收盘卖出
            net_pct = open_pct - 0.11  # 扣除交易成本

            pred = PREDICTIONS[pure_code]
            should_buy = pred["action"] == "Buy" or pred["rating"] == "Overweight"

            # 判断结果
            if should_buy and close_pct >= 1.0:
                verdict = "✅ 命中 (预测Buy, 实盘涨≥1%)"
            elif should_buy and close_pct >= 0:
                verdict = "🟡 半命中 (预测Buy, 实盘小涨但未达1%)"
            elif should_buy and close_pct < 0:
                verdict = "❌ 误判 (预测Buy, 实盘下跌)"
            elif not should_buy and close_pct < 0:
                verdict = "✅ 回避正确 (预测Hold, 实盘下跌)"
            elif not should_buy and close_pct < 1.0:
                verdict = "✅ 回避正确 (预测Hold, 实盘涨幅不足1%)"
            elif not should_buy and close_pct >= 1.0:
                verdict = "❌ 踏空 (预测Hold, 实盘涨≥1%)"
            else:
                verdict = "➖"

            logic_short = pred.get("logic", "-")

            print(f"\n  {'─' * 50}")
            print(f"  {pure_code} {name}")
            print(f"  {'─' * 50}")
            print(f"  预测: {pred['rating']:12s} | 信心: {pred['confidence']:.0%}")
            if logic_short != "-":
                print(f"  逻辑: {logic_short}")
            print(f"  Day0收盘: {d0:.2f}")
            print(f"  Day1区间: {d1['open']:.2f} → {d1['close']:.2f} (高{d1['high']:.2f} 低{d1['low']:.2f})")
            print(f"  涨跌幅:   {close_pct:+.2f}%")
            print(f"  开盘买入: {open_pct:+.2f}% (净收益: {net_pct:+.2f}%)")
            print(f"  结果:     {verdict}")

        except Exception as e:
            print(f"\n  {pure_code} {name}: 获取失败 - {e}")

    # 汇总
    print("\n" + "=" * 72)
    print("  回测汇总")
    print("=" * 72)

    hit, avoid, miss, step_on = 0, 0, 0, 0
    for sid, name in STOCKS:
        pred = PREDICTIONS[sid[2:]]
        should_buy = pred["action"] == "Buy" or pred["rating"] == "Overweight"
        try:
            url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sid},day,,,5,qfq"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=5)
            data = json.loads(resp.read().decode("utf-8"))
            klines = data["data"][sid]["qfqday"]
            d0_val = d1_val = None
            for k in klines:
                if k[0] == "2026-06-22":
                    d0_val = float(k[2])
                if k[0] == "2026-06-23":
                    d1_val = float(k[2])
            if d0_val and d1_val:
                chg = (d1_val / d0_val - 1) * 100
                if should_buy and chg >= 1.0:
                    hit += 1
                elif should_buy and chg < 1.0:
                    miss += 1
                elif not should_buy and chg >= 1.0:
                    step_on += 1
                elif not should_buy and chg < 1.0:
                    avoid += 1
        except Exception as e:
            print(f"  汇总 {sid} 失败: {e}")

    total_usable = hit + avoid + miss + step_on
    if total_usable:
        print(f"  标的: {total_usable} 支")
        print(f"  ✅ 命中 (Buy→涨≥1%):    {hit}")
        print(f"  ✅ 正确回避 (Hold→不达1%): {avoid}")
        print(f"  ❌ 误判 (Buy→跌/不达标):  {miss}")
        print(f"  ❌ 踏空 (Hold→涨≥1%):    {step_on}")
        accuracy = (hit + avoid) / total_usable * 100
        print(f"  准确率: {accuracy:.0f}% ({hit+avoid}/{total_usable})")


if __name__ == "__main__":
    main()
