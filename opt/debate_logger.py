"""debate_logger.py — 辩论轨迹分版本落盘

在 SkillOpt pipeline 每次运行时，将涉及的所有股票的完整辩论轨迹
从 data/agent_cache/ 归档到 opt/trajectories/{run_id}/ 目录。

用途: 复盘时对比不同版本之间的辩论质量变化，追溯 MISS/STEP 的根因。
"""

import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

PROJECT_DIR = Path(__file__).parent.parent
AGENT_CACHE_DIR = PROJECT_DIR / "data" / "agent_cache"
TRAJECTORIES_DIR = PROJECT_DIR / "opt" / "trajectories"
INPUT_DIR = PROJECT_DIR / "opt" / "input"
OUTPUT_DIR = PROJECT_DIR / "opt" / "output"


def _extract_symbol_date_pairs(rollout_data: dict) -> List[Dict]:
    """从 rollout 数据中提取唯一的 (code, trade_date, stock_name, sector, verdict) 五元组。"""
    results = rollout_data.get("rollout_results", [])
    seen = set()
    pairs = []
    for r in results:
        key = (r["stock"], r["date"])
        if key not in seen:
            seen.add(key)
            pairs.append({
                "code": r["stock"],
                "date": r["date"],
                "name": r.get("name", ""),
                "sector": r.get("sector", ""),
                "verdict": r.get("verdict", ""),
            })
    return pairs


def _find_trace_files(symbol: str, trade_date: str) -> Optional[Dict[str, Path]]:
    """查找某只股票某日的辩论轨迹文件。"""
    agent_dir = AGENT_CACHE_DIR / symbol
    json_path = agent_dir / "{}_agent_trace.cache.json".format(trade_date)
    md_path = agent_dir / "{}_agent_trace.md".format(trade_date)

    if json_path.exists() or md_path.exists():
        return {"json": json_path if json_path.exists() else None,
                "md": md_path if md_path.exists() else None}
    return None


def _generate_readme(run_id: str, rollout_data: dict, trace_summary: list,
                     edits_data: Optional[dict] = None) -> str:
    """生成该版本的 README.md 摘要。"""
    overall = rollout_data.get("group_summary", {}).get("overall", {})
    date_range = rollout_data.get("date_range", "?")

    lines = [
        "# SkillOpt 辩论轨迹 — 版本 {}".format(run_id),
        "",
        "**生成时间**: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "**回测日期范围**: {}".format(date_range),
        "",
        "## 回测摘要",
        "",
        "| 指标 | 值 |",
        "|------|-----|",
        "| 总样本 | {} |".format(overall.get("total", 0)),
        "| 命中 (HIT) | {} |".format(overall.get("hit", 0)),
        "| 规避 (AVOID) | {} |".format(overall.get("avoid", 0)),
        "| 踏空 (MISS) | {} |".format(overall.get("miss", 0)),
        "| 漏判 (STEP) | {} |".format(overall.get("step", 0)),
        "| 准确率 | {}% |".format(overall.get("accuracy", 0)),
        "",
        "## 板块明细",
        "",
        "| 板块 | 总 | HIT | AVOID | MISS | STEP | 准确率 |",
        "|------|----|-----|-------|------|------|--------|",
    ]

    for sector, s in rollout_data.get("group_summary", {}).get("by_sector", {}).items():
        lines.append("| {} | {} | {} | {} | {} | {} | {}% |".format(
            sector, s["total"], s["hit"], s["avoid"], s["miss"], s["step"], s["accuracy"]
        ))

    lines.append("")
    lines.append("## 错误案例速览")
    lines.append("")

    miss_cases = [t for t in trace_summary if t.get("verdict") == "MISS"]
    step_cases = [t for t in trace_summary if t.get("verdict") == "STEP"]

    if miss_cases:
        lines.append("### MISS (买入但下跌，共{}个)".format(len(miss_cases)))
        lines.append("")
        for c in miss_cases:
            lines.append("- **{}** ({}) — {} | [查看轨迹](traces/{}/{}_{}_agent_trace.md)".format(
                c.get("name", c["code"]), c["code"], c.get("sector", ""),
                c["code"], c["code"], c["date"]
            ))
        lines.append("")

    if step_cases:
        lines.append("### STEP (未买入但涨了，共{}个)".format(len(step_cases)))
        lines.append("")
        for c in step_cases:
            lines.append("- **{}** ({}) — {} | [查看轨迹](traces/{}/{}_{}_agent_trace.md)".format(
                c.get("name", c["code"]), c["code"], c.get("sector", ""),
                c["code"], c["code"], c["date"]
            ))
        lines.append("")

    if edits_data:
        edits = edits_data.get("edits", [])
        if edits:
            lines.append("## 本版本编辑提案")
            lines.append("")
            lines.append("**分析**: {}".format(edits_data.get("analysis", "N/A")[:200]))
            lines.append("")
            for i, e in enumerate(edits):
                lines.append("### 编辑 {}: {}.skill.md @ {}".format(
                    i + 1, e.get("file", "?"), e.get("section", "?")))
                lines.append("- 操作: {}".format(e.get("action", "?")))
                if e.get("reason"):
                    lines.append("- 理由: {}".format(e["reason"]))
                if e.get("new"):
                    lines.append("- 新内容: `{}`".format(e["new"][:200]))
                lines.append("")

    lines.append("## 轨迹文件清单")
    lines.append("")
    for t in trace_summary:
        verdict_emoji = {"HIT": "✅", "AVOID": "🟢", "MISS": "❌", "STEP": "⚠️"}.get(t.get("verdict", ""), "❓")
        lines.append("- {} **{}** ({}) — {} [json](traces/{}/{}_{}_agent_trace.cache.json) | [md](traces/{}/{}_{}_agent_trace.md)".format(
            verdict_emoji,
            t.get("name", t["code"]), t["code"],
            t.get("sector", ""),
            t["code"], t["code"], t["date"],
            t["code"], t["code"], t["date"]
        ))

    return "\n".join(lines)


def save_trajectories(rollout_data: dict, run_id: str = None,
                      edits_data: dict = None) -> dict:
    """将辩论轨迹归档到版本目录。

    Args:
        rollout_data: collector.collect() 的输出
        run_id: 版本标识，默认用时间戳自动生成
        edits_data: optimizer 的输出（可选，在 optimize 之后调用时传入）

    Returns:
        {"run_id": str, "version_dir": str, "saved": int, "missed": int, "summary": [...]}
    """
    if run_id is None:
        run_id = datetime.now().strftime("v%Y%m%d_%H%M%S")

    version_dir = TRAJECTORIES_DIR / run_id
    traces_dir = version_dir / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)

    pairs = _extract_symbol_date_pairs(rollout_data)

    saved_count = 0
    missed_count = 0
    trace_summary = []

    for p in pairs:
        trace_files = _find_trace_files(p["code"], p["date"])

        if trace_files is None:
            missed_count += 1
            trace_summary.append({**p, "traced": False})
            continue

        stock_traces_dir = traces_dir / p["code"]
        stock_traces_dir.mkdir(parents=True, exist_ok=True)

        for ext, src_path in trace_files.items():
            if src_path and src_path.exists():
                dst_name = "{}_{}_agent_trace.{}".format(p["code"], p["date"],
                    "cache.json" if ext == "json" else "md")
                dst_path = stock_traces_dir / dst_name
                shutil.copy2(src_path, dst_path)

        saved_count += 1
        trace_summary.append({**p, "traced": True})

    # 保存 rollout.json 到此版本目录
    rollout_dst = version_dir / "rollout.json"
    rollout_dst.write_text(
        json.dumps(rollout_data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    # 如果提供了 edits，也保存
    if edits_data:
        edits_dst = version_dir / "edits.json"
        edits_dst.write_text(
            json.dumps(edits_data, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    # 生成 README
    readme = _generate_readme(run_id, rollout_data, trace_summary, edits_data)
    (version_dir / "README.md").write_text(readme, encoding="utf-8")

    print("Trajectories saved: {}/{} stocks traced → {}".format(
        saved_count, len(pairs), version_dir))

    return {
        "run_id": run_id,
        "version_dir": str(version_dir),
        "saved": saved_count,
        "missed": missed_count,
        "summary": trace_summary,
    }


def list_versions() -> List[Dict]:
    """列出所有已保存的版本。"""
    if not TRAJECTORIES_DIR.exists():
        return []

    versions = []
    for vdir in sorted(TRAJECTORIES_DIR.iterdir()):
        if vdir.is_dir():
            readme = vdir / "README.md"
            rollout = vdir / "rollout.json"
            versions.append({
                "run_id": vdir.name,
                "has_readme": readme.exists(),
                "has_rollout": rollout.exists(),
            })
    return versions


if __name__ == "__main__":
    rollout_path = INPUT_DIR / "rollout.json"
    if not rollout_path.exists():
        print("No rollout.json found. Run collector first.")
        exit(1)

    data = json.loads(rollout_path.read_text(encoding="utf-8"))
    result = save_trajectories(data)

    print(json.dumps(result, ensure_ascii=False, indent=2))
