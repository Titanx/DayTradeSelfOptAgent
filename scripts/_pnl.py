"""四轮止损线对比: -3% vs -5%"""
import json,re
from pathlib import Path

RR = Path(__file__).parent.parent / "data" / "results"

# (code, name, d1_open, d2_high, d2_low, d2_close)
ROUNDS={
    "7/3":  [("002202","金风科技",24.73,23.70,22.03,22.19),
             ("603606","东方电缆",43.32,42.23,40.30,40.56),
             ("000977","浪潮信息",66.40,73.23,68.70,71.06),
             ("300308","中际旭创",1136.54,1138.20,1089.00,1121.90),
             ("300033","同花顺",250.50,243.00,235.01,236.20),
             ("002460","赣锋锂业",63.19,64.17,61.25,61.44),
             ("002415","海康威视",34.14,34.82,33.42,33.86),
             ("002236","大华股份",16.73,16.82,16.29,16.43)],
    "7/6":  [("603606","东方电缆",42.23,42.23,40.30,40.96)],
    "7/7":  [("000977","浪潮信息",78.17,85.99,82.03,85.99),
             ("300033","同花顺",237.51,231.50,224.00,230.30)],
    "7/8":  [("300496","中科创达",58.70,62.31,58.68,59.90)],
}

def trade(d1o,d2h,d2l,d2c,stop_pct):
    h=d1o*1.01; s=d1o*(1+stop_pct)
    if d2h>=h:     return 0.01, "止盈+1%"
    elif d2l<=s:   return stop_pct, f"止损{stop_pct*100:+.0f}%"
    else:          return (d2c/d1o-1), "收盘平仓"

print("="*65)
print("  四轮 止损-3% vs 止损-5% 对比 (100万总仓)")
print("="*65)
print(f"{'轮次':<6} {'信号':<10} {'收盘盈亏':<9} {'-3%盈亏':<9} {'-5%盈亏':<9} {'出局方式(-3%)':<16} {'出局方式(-5%)'}")
print(f"{'─'*6} {'─'*10} {'─'*9} {'─'*9} {'─'*9} {'─'*16} {'─'*16}")

tot3=tot5=0
for label, signals in ROUNDS.items():
    r3=r5=0
    for code,name,d1o,d2h,d2l,d2c in signals:
        p3, how3 = trade(d1o,d2h,d2l,d2c, -0.03)
        p5, how5 = trade(d1o,d2h,d2l,d2c, -0.05)
        close_p = (d2c/d1o-1)
        r3+=p3; r5+=p5
        m3="🟢" if p3>0 else ("🔴" if p3<0 else "⚪")
        m5="🟢" if p5>0 else ("🔴" if p5<0 else "⚪")
        print(f"  {label:<6} {code} {name:<6} {close_p:>+7.2f}%   {m3}{p3:>+6.2f}%   {m5}{p5:>+6.2f}%   {how3:<16} {how5}")
    print(f"  {'─'*6} {'─'*10} {'─'*9} {'─'*9} {'─'*9} {'─'*16} {'─'*16}")
    n=len(signals)
    print(f"  {label:<6} 平均        {r3/n:>+6.2f}%   {r5/n:>+6.2f}%")
    print()
    tot3+=r3; tot5+=r5

total_signals=sum(len(s) for s in ROUNDS.values())
print(f"  {'合计':<6} {total_signals}只信号       {tot3/total_signals:>+6.2f}%   {tot5/total_signals:>+6.2f}%  (每信号平均)")
print()

# 对比-3% vs -5%对每只的改善
print("─"*55)
print("  止损扩到-5%的改善/恶化")
print("─"*55)
for label, signals in ROUNDS.items():
    for code,name,d1o,d2h,d2l,d2c in signals:
        p3,_=trade(d1o,d2h,d2l,d2c,-0.03)
        p5,_=trade(d1o,d2h,d2l,d2c,-0.05)
        diff=p5-p3
        m="✅" if diff>0 else ("🔻" if diff<0 else "➡️")
        print(f"  {m} {code} {name:<6}  -3%={p3:+.2f}%  -5%={p5:+.2f}%  diff={diff:+.2f}pp")
print()
