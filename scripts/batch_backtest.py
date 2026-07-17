"""批量回测 (A股T+1 + 止损)
D+0预测 → D+1买入 → D+2卖出
  HIT  = 看多 + D2高 ≥ 买+1% → 止盈
  STOP = 看多 + D2低 ≤ 买-3% → 止损
  FLAT = 看多 + 未触发 → 收盘平仓
  AVOID = 观望 ok | STEP = 观望踏空
"""
import json, urllib.request, sys
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))
RESULTS_DIR = PROJECT_DIR / "data" / "results"

# H2: 从 config 读取止盈止损参数，与 collector.py / trading_graph.py 保持同步
from config.default_config import get_config as _get_cfg
_swing_cfg = _get_cfg().get("one_day_swing", {})
TARGET_GAIN_PCT = _swing_cfg.get("target_gain_pct", 1.0)   # 止盈线 +1%
STOP_LOSS_PCT = _swing_cfg.get("stop_loss_pct", 3.0)       # 止损线 -3%

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

DATE_GROUPS = [
    ("6/29(一)","2026-06-29","2026-06-30","2026-07-01"),
    ("6/30(二)","2026-06-30","2026-07-01","2026-07-02"),
    ("7/1(三)","2026-07-01","2026-07-02","2026-07-03"),
    ("7/2(四)","2026-07-02","2026-07-03","2026-07-06"),
    ("7/3(五)","2026-07-03","2026-07-06","2026-07-07"),
]


def get_klines(code):
    c = code[2:] if len(code)>6 else code
    sid = ("sh" if c.startswith(("6","9")) else "sz")+c
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sid},day,,,12,qfq"
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read().decode("utf-8"))["data"][sid]
        # (open, close, high, low)
        return {k[0]:(float(k[1]),float(k[2]),float(k[3]),float(k[4]))
                for k in (data.get("qfqday") or data.get("day",[]))}
    except Exception as e:
        print(f"  拉取 {code} K线失败: {e}")
        return {}


def load_pred(code, d0):
    for f in RESULTS_DIR.glob(f"{code}_{d0}_*analysis.cache.json"):
        d = json.loads(f.read_text(encoding="utf-8"))
        return {"rating":d.get("rating","?"),"conf":d.get("confidence",0)}


def main():
    print("=" * 78)
    print("  Batch回测 (T+1 + 止盈1% / 止损-3%)")
    print("=" * 78)

    all_results = {}
    for label, d0, d1, d2 in DATE_GROUPS:
        hit=avoid=step=flat=stop=0
        for code,name,sector in STOCKS:
            pred=load_pred(code,d0)
            k=get_klines(code)
            if not pred or d0 not in k or d1 not in k or d2 not in k: continue
            is_bull=pred["rating"].lower() in ("buy","overweight")
            d1o=k[d1][0]; d2h=k[d2][2]; d2l=k[d2][3]; d2c=k[d2][1]
            # H2: 从 config 读取止盈止损参数，避免与 config 修改不同步
            hit_p=d1o*(1+TARGET_GAIN_PCT/100.0); stop_p=d1o*(1-STOP_LOSS_PCT/100.0)
            # H1: STEP 基准与 collector.py 对齐，用 d1_open（买入价）而非 d0_close
            step_trig=(d2h/d1o-1)*100>=TARGET_GAIN_PCT

            if is_bull and d2h>=hit_p:     hit+=1
            elif is_bull and d2l<=stop_p:  stop+=1
            elif is_bull:                   flat+=1
            elif step_trig:                 step+=1
            else:                           avoid+=1

        valid=hit+avoid+flat+stop+step
        bull=hit+stop+flat
        pnl=hit*0.01 + stop*(-0.03)
        # can't compute flat pnl in batch easily, skip for summary
        all_results[label]={"N":valid,"HIT":hit,"STOP":stop,"FLAT":flat,
            "AVOID":avoid,"STEP":step,"BULL":bull}
        print(f"  {label}: 有效{valid} HIT={hit} STOP={stop} FLAT={flat} AVOID={avoid} STEP={step} | 看多{bull}只")

    print(f"\n{'='*78}")
    print(f"  五 天  汇  总")
    print(f"{'='*78}")
    print(f"  {'日期':<8} {'样本':<4} {'HIT':<4} {'STOP':<5} {'FLAT':<5} {'AVOID':<5} {'STEP':<4} {'看多':<4}")
    print(f"  {'─'*8} {'─'*4} {'─'*4} {'─'*5} {'─'*5} {'─'*5} {'─'*4} {'─'*4}")
    for label in [g[0] for g in DATE_GROUPS]:
        r=all_results[label]
        print(f"  {label:<8} {r['N']:<4} {r['HIT']:<4} {r['STOP']:<5} {r['FLAT']:<5} {r['AVOID']:<5} {r['STEP']:<4} {r['BULL']:<4}")
    tN=sum(r["N"] for r in all_results.values())
    tH=sum(r["HIT"] for r in all_results.values())
    tS=sum(r["STOP"] for r in all_results.values())
    tF=sum(r["FLAT"] for r in all_results.values())
    tA=sum(r["AVOID"] for r in all_results.values())
    tSt=sum(r["STEP"] for r in all_results.values())
    tB=sum(r["BULL"] for r in all_results.values())
    print(f"  {'─'*8} {'─'*4} {'─'*4} {'─'*5} {'─'*5} {'─'*5} {'─'*4} {'─'*4}")
    print(f"  {'合计':<8} {tN:<4} {tH:<4} {tS:<5} {tF:<5} {tA:<5} {tSt:<4} {tB:<4}")
    print()


if __name__ == "__main__":
    main()
