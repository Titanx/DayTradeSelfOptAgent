"""批量回测: 上周一到周四 (A股T+1真实约束)
D+0预测 → D+1开盘买入 → D+2日内最高止盈(≥买入价+1%)
HIT=看多+止盈成功 | MISS=看多+止盈失败 | AVOID=观望+未触发 | STEP=观望+涨≥1%
"""
import json, urllib.request, sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))
RESULTS_DIR = PROJECT_DIR / "data" / "results"

STOCKS = [
    ("600438","通威股份","光伏"),("601012","隆基绿能","光伏"),("300274","阳光电源","光伏"),
    ("688599","天合光能","光伏"),("300751","迈为股份","光伏"),("002459","晶澳科技","光伏"),
    ("603806","福斯特","光伏"),("300763","锦浪科技","光伏"),("600732","爱旭股份","光伏"),
    ("688390","固德威","光伏"),("002202","金风科技","风电"),("601615","明阳智能","风电"),
    ("603606","东方电缆","风电"),("300850","新强联","风电"),("001289","龙源电力","风电"),
    ("002531","天顺风能","风电"),("300772","运达股份","风电"),("002080","中材科技","风电"),
    ("002487","大金重工","风电"),("300129","泰胜风能","风电"),("002230","科大讯飞","AI"),
    ("688256","寒武纪","AI"),("000977","浪潮信息","AI"),("300308","中际旭创","AI"),
    ("300033","同花顺","AI"),("601360","三六零","AI"),("300418","昆仑万维","AI"),
    ("300229","拓尔思","AI"),("688041","海光信息","AI"),("688327","云从科技","AI"),
    ("300750","宁德时代","储能"),("300014","亿纬锂能","储能"),("002074","国轩高科","储能"),
    ("002460","赣锋锂业","储能"),("601727","上海电气","储能"),("300073","当升科技","储能"),
    ("688063","派能科技","储能"),("300207","欣旺达","储能"),("300438","鹏辉能源","储能"),
    ("300068","南都电源","储能"),("002415","海康威视","视觉"),("002236","大华股份","视觉"),
    ("002920","德赛西威","视觉"),("300496","中科创达","视觉"),("603501","韦尔股份","视觉"),
    ("002456","欧菲光","视觉"),("688088","虹软科技","视觉"),("688207","格灵深瞳","视觉"),
    ("688400","凌云光","视觉"),("688686","奥普特","视觉"),
]

# 日期组: (标签, D0预测日, D1买入日, D2卖出日)
DATE_GROUPS = [
    ("6/29(一)", "2026-06-29", "2026-06-30", "2026-07-01"),
    ("6/30(二)", "2026-06-30", "2026-07-01", "2026-07-02"),
    ("7/1(三)",  "2026-07-01", "2026-07-02", "2026-07-03"),
    ("7/2(四)",  "2026-07-02", "2026-07-03", "2026-07-06"),
]


def get_klines(code):
    c = code[2:] if len(code) > 6 else code
    sid = ("sh" if c.startswith(("6","9")) else "sz") + c
    url = "http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sid},day,,,12,qfq".format(sid=sid)
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))["data"][sid]
        return {k[0]: (float(k[1]), float(k[2]), float(k[3])) for k in (data.get("qfqday") or data.get("day",[]))}
    except:
        return {}


def load_pred(code, d0):
    for f in RESULTS_DIR.glob(f"{code}_{d0}_*analysis.cache.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        return {"rating": d.get("rating","?"), "conf": d.get("confidence",0)}


def pct(v1, v2):
    return (v2/v1 - 1)*100


print("=" * 78)
print("  Batch回测: 上周一到周四 (A股T+1真实约束)")
print("  D+0收盘预测 → D+1开盘买入 → D+2日内最高止盈(≥+1%)")
print("=" * 78)

all_results = {}

for label, d0, d1, d2 in DATE_GROUPS:
    hit = avoid = miss = step = 0
    for code, name, sector in STOCKS:
        pred = load_pred(code, d0)
        k = get_klines(code)
        if not pred or d0 not in k or d1 not in k or d2 not in k:
            continue
        is_bull = pred["rating"].lower() in ("buy","overweight")
        open_buy, _, d2_high = k[d1][0], None, k[d2][2]

        can_exit = pct(open_buy, d2_high) >= 1.0
        step_trigger = pct(k[d0][1], d2_high) >= 1.0

        if is_bull and can_exit:       hit += 1
        elif is_bull:                   miss += 1
        elif step_trigger:              step += 1
        else:                           avoid += 1

    valid = hit + avoid + miss + step
    acc = (hit+avoid)/valid*100 if valid else 0
    buy_hit = f"{hit}/{hit+miss}" if hit+miss>0 else "-"

    all_results[label] = {"N":valid, "HIT":hit, "AVOID":avoid, "MISS":miss, "STEP":step, "ACC":acc, "BUY":buy_hit}
    print(f"\n  {label}: D0={d0} → D1={d1} → D2={d2}")
    print(f"    有效:{valid} | HIT:{hit} AVOID:{avoid} MISS:{miss} STEP:{step} | 准确率:{acc:.0f}% | Buy命中:{buy_hit}")

# ==== 汇总表 ====
print(f"\n{'=' * 78}")
print(f"  四天汇总")
print(f"{'=' * 78}")
print(f"  {'日期':<8} {'样本':<5} {'HIT':<5} {'AVOID':<6} {'MISS':<5} {'STEP':<5} {'准确率':<6} {'Buy命中':<8}")
print(f"  {'─'*8} {'─'*5} {'─'*5} {'─'*6} {'─'*5} {'─'*5} {'─'*6} {'─'*8}")
for label in [g[0] for g in DATE_GROUPS]:
    r = all_results[label]
    print(f"  {label:<8} {r['N']:<5} {r['HIT']:<5} {r['AVOID']:<6} {r['MISS']:<5} {r['STEP']:<5} {r['ACC']:<5.0f}%  {r['BUY']:<8}")

# 合计
tN = sum(r["N"] for r in all_results.values())
tH = sum(r["HIT"] for r in all_results.values())
tA = sum(r["AVOID"] for r in all_results.values())
tM = sum(r["MISS"] for r in all_results.values())
tS = sum(r["STEP"] for r in all_results.values())
tAcc = (tH+tA)/tN*100 if tN else 0
tBuy = f"{tH}/{tH+tM}" if tH+tM>0 else "-"
print(f"  {'─'*8} {'─'*5} {'─'*5} {'─'*6} {'─'*5} {'─'*5} {'─'*6} {'─'*8}")
print(f"  {'合计':<8} {tN:<5} {tH:<5} {tA:<6} {tM:<5} {tS:<5} {tAcc:<5.0f}%  {tBuy:<8}")
print()
