"""
批量分析脚本 — AStockAgent Batch Runner

对光伏/风电/AI/储能/视觉 ~110支股票依次分析
每支股票:
  - results/{code}/{timestamp}_analysis.json  (完整JSON结果)
  - results/{code}/{timestamp}_thinking.md   (思考过程+报告)
"""

import os
import sys
import json
import time
import traceback
import signal
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any

project_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(project_dir))

from config.default_config import get_config
from graph.trading_graph import AStockTradingGraph
from dataflows.akshare_adapter import get_latest_trade_date
from dataflows.market_cache import MarketDataCache

# ============================================================
# 股票列表: ~110支 (光伏25 + 风电20 + AI 25 + 储能20 + 视觉20)
# ============================================================
STOCKS = [
    # === ☀️ 光伏 (5) ===
    ("600438", "通威股份", "光伏"),       # 硅料+电池片龙头
    ("601012", "隆基绿能", "光伏"),       # 硅片龙头
    ("300274", "阳光电源", "光伏"),       # 逆变器龙头
    ("688599", "天合光能", "光伏"),       # 组件龙头
    ("300751", "迈为股份", "光伏"),       # 电池片设备龙头

    # === 💨 风电 (5) ===
    ("002202", "金风科技", "风电"),       # 风机龙头
    ("601615", "明阳智能", "风电"),       # 海上风机龙头
    ("603606", "东方电缆", "风电"),       # 海缆龙头
    ("300850", "新强联", "风电"),         # 主轴轴承龙头
    ("001289", "龙源电力", "风电"),       # 风电运营龙头

    # === 🧠 AI (5) ===
    ("002230", "科大讯飞", "AI"),         # AI语音龙头
    ("688256", "寒武纪", "AI"),           # AI芯片龙头
    ("000977", "浪潮信息", "AI"),         # AI服务器龙头
    ("300308", "中际旭创", "AI"),         # 光模块龙头
    ("300033", "同花顺", "AI"),           # AI金融应用龙头

    # === 🔋 储能 (5) ===
    ("300750", "宁德时代", "储能"),       # 动力电池+储能龙头
    ("300014", "亿纬锂能", "储能"),       # 锂电池龙头
    ("002074", "国轩高科", "储能"),       # 储能电池龙头
    ("002460", "赣锋锂业", "储能"),       # 锂资源龙头
    ("601727", "上海电气", "储能"),       # 储能系统集成龙头

    # === 👁️ 视觉 (5) ===
    ("002415", "海康威视", "视觉"),       # 安防视觉龙头
    ("002236", "大华股份", "视觉"),       # 安防视觉第二
    ("002920", "德赛西威", "视觉"),       # 汽车视觉龙头
    ("300496", "中科创达", "视觉"),       # 智能视觉OS
    ("603501", "韦尔股份", "视觉"),       # CIS芯片龙头
]

# 去重
seen = set()
unique_stocks = []
for s in STOCKS:
    if s[0] not in seen:
        unique_stocks.append(s)
        seen.add(s[0])
STOCKS = unique_stocks

# ============================================================
# 运行配置
# ============================================================
TRADE_DATE = get_latest_trade_date()
print(f"📅 最近交易日: {TRADE_DATE}")
BATCH_ID = datetime.now().strftime("%Y%m%d_%H%M%S")
RESULTS_BASE = Path.home() / ".astock_agent" / "batch_results"

# ============================================================
# 主逻辑
# ============================================================

def save_thinking_md(output_dir: Path, symbol: str, name: str, result: dict, ts: str) -> Path:
    """保存思考过程 Markdown"""
    lines = []

    # 标题
    rating = result.get("rating", "?")
    action = result.get("action", "?")
    conf = result.get("confidence", 0)
    emoji = {"Buy": "🟢", "Overweight": "🟡", "Hold": "⚪", "Underweight": "🟠", "Sell": "🔴"}

    lines.append(f"# {emoji.get(rating, '⚪')} {name}({symbol}) 分析思考过程")
    lines.append(f"")
    lines.append(f"**分析日期**: {ts}")
    lines.append(f"**所属赛道**: {result.get('sector', '')}")
    lines.append(f"**最终评级**: {rating}")
    lines.append(f"**建议动作**: {action}")
    lines.append(f"**信心度**: {conf:.0%}")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"")

    # 各Agent报告
    reports = result.get("reports", {})
    report_titles = {
        "fundamental": "📊 基本面分析",
        "technical": "📈 技术面分析",
        "sentiment": "📡 舆论情绪分析",
        "policy": "🏛️ 政策面分析",
    }

    for key, title in report_titles.items():
        content = reports.get(key, "")
        if content and len(content) > 20:
            lines.append(f"## {title}")
            lines.append(f"")
            # 截断过长的内容，但保留足够信息
            if len(content) > 8000:
                content = content[:8000] + "\n\n...(内容过长，已截断，完整内容见JSON)"
            lines.append(content)
            lines.append(f"")
            lines.append(f"---")
            lines.append(f"")

    # 最终决策
    lines.append(f"## 🎯 最终决策")
    lines.append(f"")
    decision = result.get("decision", "")
    if decision:
        if len(decision) > 5000:
            decision = decision[:5000] + "\n\n...(完整决策见JSON)"
        lines.append(decision)
    lines.append(f"")

    # 写入文件
    filepath = output_dir / f"{ts}_thinking.md"
    filepath.write_text("\n".join(lines), encoding="utf-8")
    return filepath


def analyze_one(symbol: str, name: str, sector: str,
                agent: AStockTradingGraph  # Removed type hint to avoid import issues
                ) -> Dict[str, Any]:
    """分析单支股票"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = RESULTS_BASE / symbol
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = agent.analyze(symbol, TRADE_DATE, name)
        result["sector"] = sector
        result["batch_id"] = BATCH_ID

        # 保存 JSON
        json_path = output_dir / f"{ts}_analysis.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        # 保存 Thinking MD
        md_path = save_thinking_md(output_dir, symbol, name, result, ts)

        return {
            "symbol": symbol,
            "name": name,
            "sector": sector,
            "rating": result.get("rating", "?"),
            "action": result.get("action", "?"),
            "confidence": result.get("confidence", 0),
            "json_path": str(json_path),
            "md_path": str(md_path),
            "status": "success",
            "error": None,
        }

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        trace = traceback.format_exc()

        # 保存错误信息
        error_result = {
            "symbol": symbol,
            "name": name,
            "sector": sector,
            "trade_date": TRADE_DATE,
            "error": error_msg,
            "traceback": trace,
            "batch_id": BATCH_ID,
        }
        error_path = output_dir / f"{ts}_error.json"
        with open(error_path, "w", encoding="utf-8") as f:
            json.dump(error_result, f, ensure_ascii=False, indent=2)

        return {
            "symbol": symbol,
            "name": name,
            "sector": sector,
            "rating": "?",
            "action": "?",
            "confidence": 0,
            "json_path": str(error_path),
            "md_path": "",
            "status": "error",
            "error": error_msg,
        }


def main():
    config = get_config()
    config["debug"] = False
    config["max_risk_discuss_rounds"] = 2  # 风险辩论 2 轮，确保评级差异化
    config["enable_opinion_monitor"] = True

    # 跳过已有结果的股票
    todo = []
    skipped = []
    for code, name, sector in STOCKS:
        dir = RESULTS_BASE / code
        if dir.exists() and any(f.endswith('_analysis.json') for f in os.listdir(dir) if not f.startswith('_')):
            skipped.append(f"{name}({code})")
        else:
            todo.append((code, name, sector))

    print("=" * 70)
    print(f"  AStockAgent 批量分析")
    print(f"  批次ID: {BATCH_ID}")
    print(f"  分析日期: {TRADE_DATE}")
    print(f"  总股票: {len(STOCKS)} 支 | 已跳过: {len(skipped)} 支 | 待分析: {len(todo)} 支")
    print("=" * 70)
    if skipped:
        print(f"  跳过: {', '.join(skipped[:10])}{'...' if len(skipped) > 10 else ''}")
    print()

    if not todo:
        print("✅ 所有股票已完成!")
        return []

    # 创建 Agent
    print("初始化 AStockAgent...")
    agent = AStockTradingGraph(config=config, debug=False)
    print("OK\n")

    # ———— 预加载市场公共数据到缓存 ————
    cache = MarketDataCache.get_instance()
    cache.set_trade_date(TRADE_DATE)
    print("📦 预加载市场公共数据...")
    preload_status = cache.preload()
    for method, status in preload_status.items():
        print(f"  {status} {method}")
    print()

    results = []
    success_count = 0
    error_count = 0
    start_time = time.time()

    for i, (symbol, name, sector) in enumerate(todo, 1):
        elapsed = time.time() - start_time
        eta = (elapsed / max(i - 1, 1)) * (len(todo) - i + 1) if i > 1 else 0

        print(f"[{i:3d}/{len(todo)}] {symbol} {name} ({sector}) "
              f"| 已用 {elapsed/60:.1f}分 | 预计剩余 {eta/60:.1f}分")

        item = analyze_one(symbol, name, sector, agent)

        rating_emoji = {"Buy": "🟢", "Overweight": "🟡", "Hold": "⚪",
                        "Underweight": "🟠", "Sell": "🔴"}.get(item["rating"], "❓")

        if item["status"] == "success":
            success_count += 1
            print(f"    ✅ {rating_emoji} {item['rating']} "
                  f"(置信度: {item['confidence']:.0%})")
        else:
            error_count += 1
            print(f"    ❌ {item['error'][:100]}")

        results.append(item)

        # 批次总结进度
        if i % 10 == 0:
            print(f"    --- [{i}/{len(todo)}] 已完成: {success_count}成功, "
                  f"{error_count}失败 ---\n")

        # 间隔1秒，避免API限流
        if i < len(todo):
            time.sleep(1)

    # ============================================================
    # 最终汇总
    # ============================================================
    total_time = (time.time() - start_time) / 60
    print()
    print("=" * 70)
    print("  📊 批量分析完成！")
    print(f"  总耗时: {total_time:.1f} 分钟")
    print(f"  成功: {success_count} / {len(todo)}")
    print(f"  失败: {error_count} / {len(todo)}")
    print("=" * 70)

    # 按赛道汇总
    print()
    print("## 各赛道评级汇总")
    for sector_name in ["光伏", "风电", "AI", "储能", "视觉"]:
        sector_results = [r for r in results if r["sector"] == sector_name]
        ratings = [r["rating"] for r in sector_results if r["rating"] != "?"]

        buy_count = ratings.count("Buy") + ratings.count("Overweight")
        hold_count = ratings.count("Hold")
        sell_count = ratings.count("Sell") + ratings.count("Underweight")

        print(f"  {sector_name} ({len(sector_results)}支): "
              f"🟢{buy_count} ⚪{hold_count} 🔴{sell_count} "
              f"(成功率 {len([r for r in sector_results if r['status'] == 'success'])}/{len(sector_results)})")

    # 保存汇总
    summary = {
        "batch_id": BATCH_ID,
        "trade_date": TRADE_DATE,
        "total_count": len(STOCKS),
        "success_count": success_count,
        "error_count": error_count,
        "total_time_minutes": round(total_time, 1),
        "results": results,
    }
    summary_path = RESULTS_BASE / f"_BATCH_{BATCH_ID}_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n📁 汇总文件: {summary_path}")
    print(f"📁 各股结果: {RESULTS_BASE}/{{代码}}/")

    return results


if __name__ == "__main__":
    main()
