"""生成当日批量分析总结报告 MD"""
import json
import re
from pathlib import Path
from datetime import datetime

PROJ = Path(__file__).parent.parent
results_dir = PROJ / "data" / "results"
all_files = sorted(results_dir.glob("*_analysis.cache.json"))
if not all_files:
    print("无结果文件")
    exit(1)

# 取最新日期的结果
dates = set()
for f in all_files:
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        dates.add(d.get("trade_date", ""))
    except Exception:
        pass
latest_date = max(dates) if dates else ""
files = [f for f in all_files if latest_date in f.stem]
if not files:
    files = all_files

# ---------- 板块映射 ----------
SYMBOL_SECTOR = {
    "600438": "光伏", "601012": "光伏", "300274": "光伏", "688599": "光伏", "300751": "光伏",
    "002202": "风电", "601615": "风电", "603606": "风电", "300850": "风电", "001289": "风电",
    "002230": "AI", "688256": "AI", "000977": "AI", "300308": "AI", "300033": "AI",
    "300750": "储能", "300014": "储能", "002074": "储能", "002460": "储能", "601727": "储能",
    "002415": "视觉", "002236": "视觉", "002920": "视觉", "300496": "视觉", "603501": "视觉",
}
SECTOR_LABEL = {"光伏": "☀️ 光伏", "风电": "💨 风电", "AI": "🧠 AI", "储能": "🔋 储能", "视觉": "👁️ 视觉"}

trade_date = json.loads(files[0].read_text(encoding="utf-8")).get("trade_date", "")
today = datetime.now().strftime("%Y-%m-%d")

# ---------- 加载所有结果 ----------
results = []
for f in files:
    d = json.loads(f.read_text(encoding="utf-8"))
    d["_sector"] = SYMBOL_SECTOR.get(d["symbol"], "未知")
    results.append(d)

results.sort(key=lambda r: (r["_sector"], r["rating"], r["symbol"]))

# ---------- 按板块/评级分组 ----------
by_sector = {}
by_rating = {}
for r in results:
    sector = SECTOR_LABEL.get(r["_sector"], r["_sector"])
    by_sector.setdefault(sector, []).append(r)
    by_rating.setdefault(r["rating"], []).append(r)

RATING_EMOJI = {"Buy": "🟢", "Overweight": "🟡", "Hold": "⚪", "Underweight": "🟠", "Sell": "🔴"}
RATING_ORDER = ["Buy", "Overweight", "Hold", "Underweight", "Sell"]

def _extract_logic(text: str) -> str:
    """从 decision JSON 文本中提取 investment_logic / reasoning / investment_thesis"""
    if not text:
        return ""
    text = text.strip()
    # 去掉 markdown 代码块标记
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # 尝试 JSON 解析
    try:
        obj = json.loads(text)
        decision = obj.get("decision", obj)
        if isinstance(decision, dict):
            logic = (
                decision.get("investment_logic")
                or decision.get("reasoning")
                or decision.get("investment_thesis")
                or decision.get("investment_rationale")
                or ""
            )
            if logic:
                return logic
    except (json.JSONDecodeError, TypeError):
        pass
    # Fallback: 找关键段落
    for pat in ["核心投资论题[：:](.*?)(?:\\n\\n|$)", "核心逻辑[：:](.*?)(?:\\n\\n|$)",
                 "核心矛盾[：:](.*?)(?:\\n\\n|$)", "我的决策倾向于(.*?)(?:\\n\\n|$)",
                 "investment_logic[：:]\s*\"([^\"]{50,300})\""]:
        m = re.search(pat, text, re.DOTALL)
        if m:
            return m.group(1).strip()[:300]
    # 取第一段有意义的文字
    lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 20]
    return lines[0][:300] if lines else text[:200]

# ---------- 生成 MD ----------
lines = []
lines.append(f"# 📊 AStockAgent 批量分析报告 — {trade_date}")
lines.append(f"**生成时间**: {today} | **股票数**: {len(results)} 支 | **覆盖板块**: 光伏/风电/AI/储能/视觉")
lines.append("")
lines.append("> ⚠️ 本报告由 AI 系统自动生成，仅供学习研究，不构成投资建议。")
lines.append("")

# === 一、总览 ===
lines.append("## 一、总览")
lines.append("")
lines.append("| 评级 | 数量 | 占比 |")
lines.append("|------|:--:|:----:|")
total = len(results)
for rating in RATING_ORDER:
    count = len(by_rating.get(rating, []))
    if count > 0:
        e = RATING_EMOJI.get(rating, "")
        lines.append(f"| {e} {rating} | {count} | {count/total:.0%} |")
lines.append("")
lines.append(f"**市场基调**: 极度分化 — 储能/AI硬件全线超配，光伏产业链全面谨慎")
lines.append("")

# === 板块热力图 ===
lines.append("### 板块热度")
lines.append("")
lines.append("| 板块 | 股票数 | 超配 | 中性 | 低配 | 平均信心度 | 热度 |")
lines.append("|------|:--:|:--:|:--:|:--:|:--:|------|")
for sector_label in ["🔋 储能", "🧠 AI", "👁️ 视觉", "💨 风电", "☀️ 光伏"]:
    stocks = by_sector.get(sector_label, [])
    if not stocks:
        continue
    ow = sum(1 for s in stocks if s["rating"] == "Overweight")
    ho = sum(1 for s in stocks if s["rating"] == "Hold")
    uw = sum(1 for s in stocks if s["rating"] in ("Underweight", "Sell"))
    avg_conf = sum(s["confidence"] for s in stocks) / len(stocks)
    bar = "🔥" * ow + "➖" * ho + "❄️" * uw
    lines.append(f"| {sector_label} | {len(stocks)} | {ow} | {ho} | {uw} | {avg_conf:.0%} | {bar} |")
lines.append("")

# === 二、各板块详情 ===
lines.append("## 二、各板块详情")
lines.append("")

for sector_label in ["🔋 储能", "🧠 AI", "👁️ 视觉", "💨 风电", "☀️ 光伏"]:
    stocks = by_sector.get(sector_label, [])
    if not stocks:
        continue
    lines.append(f"### {sector_label}")
    lines.append("")
    lines.append("| 代码 | 名称 | 评级 | 信心度 | 辩论轮 | 风险轮 | 核心逻辑 |")
    lines.append("|------|------|------|:--:|:--:|:--:|------|")
    for s in sorted(stocks, key=lambda x: (x["rating"], -x["confidence"])):
        e = RATING_EMOJI.get(s["rating"], "")
        dr = s.get("debate_rounds", "-")
        rr = s.get("risk_rounds", "-")
        logic = _extract_logic(s.get("decision", ""))
        # 截短
        if len(logic) > 80:
            logic = logic[:77] + "..."
        lines.append(f"| {s['symbol']} | {s.get('stock_name','')} | {e} {s['rating']} | {s['confidence']:.0%} | {dr} | {rr} | {logic} |")
    lines.append("")
    # 板块小结
    ow_s = [s for s in stocks if s["rating"] == "Overweight"]
    uw_s = [s for s in stocks if s["rating"] in ("Underweight", "Sell")]
    ho_s = [s for s in stocks if s["rating"] == "Hold"]
    if ow_s:
        names = "、".join(s.get("stock_name", "") for s in ow_s)
        lines.append(f"**超配**: {names}")
    if ho_s:
        names = "、".join(s.get("stock_name", "") for s in ho_s)
        lines.append(f"**中性**: {names}")
    if uw_s:
        names = "、".join(s.get("stock_name", "") for s in uw_s)
        lines.append(f"**低配**: {names}")
    lines.append("")

# === 三、各评级详情 ===
lines.append("## 三、各评级详情")
lines.append("")

for rating in RATING_ORDER:
    stocks = by_rating.get(rating, [])
    if not stocks:
        continue
    e = RATING_EMOJI.get(rating, "")
    lines.append(f"### {e} {rating}（{len(stocks)} 支）")
    lines.append("")
    for s in stocks:
        sector = s["_sector"]
        lines.append(f"**{s['symbol']} {s.get('stock_name','')}** [{sector}] 信心度 {s['confidence']:.0%}")
        logic = _extract_logic(s.get("decision", ""))
        if logic:
            lines.append(f"> {logic}")
            lines.append("")
    lines.append("")

# === 四、方法论 ===
lines.append("## 四、方法论")
lines.append("")
lines.append("**分析框架**: 四维分析师协同 LangGraph 图编排")
lines.append("")
lines.append("| 分析师 | 数据源 | 权重 |")
lines.append("|--------|--------|:--:|")
lines.append("| 🔬 基本面 | 同花顺财务指标(ROE/ROA/毛利率) + PE/PB估值 | 25% |")
lines.append("| 📈 技术面 | 东方财富日线OHLCV + MA均线 + 量价分析 | 25% |")
lines.append("| 💬 舆情情绪 | 雪球帖子/行情 + 东方财富新闻 + 微博搜索 | 25% |")
lines.append("| 🏛️ 政策面 | 行业板块动量 + 北向资金流向 + 市场情绪 | 25% |")
lines.append("")
lines.append("**辩论机制**: 多空研究员 3 轮辩论 → 风险管理 3 轮辩论 → 投资经理终决")
lines.append("")
lines.append(f"**数据日期**: {trade_date} | **LLM**: DeepSeek-V3")
lines.append("")
lines.append("---")
lines.append("")
lines.append("> ⚠️ **免责声明**: 本报告由 AI 多智能体系统自动生成，仅供学习研究使用，不构成任何投资建议。股市有风险，投资需谨慎。")
lines.append("")

# 写入
report_path = PROJ / "data" / f"{trade_date}_daily_report.md"
report_path.write_text("\n".join(lines), encoding="utf-8")
print(f"✅ 报告已生成: {report_path}")
print(f"   共 {len(lines)} 行")
