"""evolve.py — EvoSkill 式收敛检测 + 新能力发现

当 SkillOpt (optimize/aggregate/select) 在 N 轮内都无法提升准确率时，
触发更深层的分析：审查全部辩论轨迹，诊断是否存在**结构性缺失**，
即当前 8-agent 架构本身是否需要新增 Agent 或技能类型。

EvoSkill 核心思想的落地:
  - 不是逐条改 prompt，而是问"缺了什么能力？"
  - 不是在已有 skill 上加规则，而是决定是否需要新 skill

触发条件 (收敛检测):
  - 最近 3 轮 pipeline accuracy 变化幅度 < 2%
  - 或者 rejected 编辑数量持续 > 0 且 applied = 0

发现流程:
  1. 加载最近 N 轮的全部辩论轨迹 (opt/trajectories/)
  2. LLM 深度分析: 哪些错误是"规则不足"vs"架构缺失"
  3. 输出 discovery.json: 是否需要新 Agent / 新 skill / 合并

Safety:
  - 只在收敛时触发，不会每轮都跑
  - 发现的提案走同一套 review/apply 管线
  - 新 skill 文件创建前需人工确认

输入:  pipeline_history.json + 辩论轨迹
输出: opt/output/discovery.json
"""

import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))
sys.path.insert(0, str(PROJECT_DIR / "libs"))
OUTPUT_DIR = PROJECT_DIR / "opt" / "output"
TRAJECTORIES_DIR = PROJECT_DIR / "opt" / "trajectories"
INPUT_DIR = PROJECT_DIR / "opt" / "input"
SKILLS_DIR = PROJECT_DIR / "skills"
HISTORY_FILE = OUTPUT_DIR / "pipeline_history.json"

CONVERGENCE_WINDOW = 3        # 连续 N 轮
CONVERGENCE_EPSILON = 2.0     # 准确率波动阈值 (%)


def _load_accuracy_history() -> List[Dict]:
    """加载 pipeline 准确率历史。"""
    if not HISTORY_FILE.exists():
        return []

    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_accuracy_history(history: List[Dict]):
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def record_run(run_id: str, rollout_data: dict, edits_data: dict = None,
               applied: bool = False, gate_result: dict = None):
    """每次 pipeline run 后记录准确率。

    Args:
        run_id: 本次运行 ID
        rollout_data: collector 输出的回测数据
        edits_data: optimizer 输出
        applied: 是否应用了编辑
        gate_result: gate 对比结果 (旧 acc → 新 acc)
    """
    overall = rollout_data.get("group_summary", {}).get("overall", {})
    accuracy = overall.get("accuracy", 0)

    entry = {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
        "accuracy": accuracy,
        "hit": overall.get("hit", 0),
        "avoid": overall.get("avoid", 0),
        "miss": overall.get("miss", 0),
        "step": overall.get("step", 0),
        "total_samples": overall.get("total", 0),
        "edits_proposed": len(edits_data.get("edits", [])) if edits_data else 0,
        "edits_applied": applied,
    }

    if gate_result:
        entry["gate_old_acc"] = gate_result.get("old_accuracy", 0)
        entry["gate_new_acc"] = gate_result.get("new_accuracy", 0)
        entry["gate_delta"] = gate_result.get("delta", 0)

    history = _load_accuracy_history()
    history.append(entry)
    _save_accuracy_history(history)

    return entry


def _recent_accuracy(history: List[Dict], n: int) -> List[float]:
    """取最近 n 轮的准确率列表。"""
    return [h["accuracy"] for h in history[-n:] if "accuracy" in h]


def detect_convergence(history: List[Dict] = None) -> Tuple[bool, str]:
    """检测 SkillOpt 是否已收敛 (改进空间耗尽)。

    Returns:
        (converged, reason)
    """
    if history is None:
        history = _load_accuracy_history()

    if len(history) < CONVERGENCE_WINDOW:
        return False, "need {}+ runs, have {}".format(CONVERGENCE_WINDOW, len(history))

    recent = _recent_accuracy(history, CONVERGENCE_WINDOW)

    if len(recent) < CONVERGENCE_WINDOW:
        return False, "insufficient accuracy data"

    acc_range = max(recent) - min(recent)

    if acc_range < CONVERGENCE_EPSILON:
        return True, "accuracy plateau: {:.1f}%~{:.1f}% (range={:.1f}%)".format(
            min(recent), max(recent), acc_range)

    if recent[-1] <= recent[-2] and recent[-2] <= recent[-3]:
        return True, "accuracy declining: {:.1f}% → {:.1f}% → {:.1f}%".format(
            recent[-3], recent[-2], recent[-1])

    return False, "accuracy still improving ({:.1f}% → {:.1f}%)".format(
        recent[0], recent[-1])


def _load_trajectory_samples(max_samples: int = 10) -> List[Dict]:
    """从最新版本目录加载有代表的辩论轨迹样本 (优先错误样本)。"""
    versions = sorted(TRAJECTORIES_DIR.glob("*"))

    if not versions:
        return []

    latest = versions[-1]
    rollout_path = latest / "rollout.json"
    if not rollout_path.exists():
        return []

    rollout = json.loads(rollout_path.read_text(encoding="utf-8"))

    error_cases = []
    good_cases = []

    for r in rollout.get("rollout_results", []):
        code = r["stock"]
        date = r["date"]
        verdict = r["verdict"]
        trace_dir = latest / "traces" / code
        md_path = trace_dir / "{}_{}_agent_trace.md".format(code, date)

        entry = {
            "code": code,
            "name": r.get("name", ""),
            "date": date,
            "sector": r.get("sector", ""),
            "verdict": verdict,
            "rating": r.get("rating", ""),
            "actual_chg": r.get("actual_chg", 0),
            "has_trace": md_path.exists(),
            "trace_path": str(md_path) if md_path.exists() else "",
        }

        if verdict in ("MISS", "STEP"):
            error_cases.append(entry)
        else:
            good_cases.append(entry)

    samples = error_cases[:max_samples]
    remaining = max_samples - len(samples)
    if remaining > 0:
        samples += good_cases[:remaining]

    for s in samples:
        if s["has_trace"]:
            try:
                trace_content = Path(s["trace_path"]).read_text(encoding="utf-8")
                s["trace_content"] = trace_content[:4000]
            except Exception:
                s["trace_content"] = "(read error)"

    return samples


def _load_current_skill_catalog() -> Dict[str, str]:
    """加载当前所有 skill 文件的摘要 (只取规则和 anti_patterns)。"""
    catalog = {}
    for sf in sorted(SKILLS_DIR.glob("*.skill.md")):
        content = sf.read_text(encoding="utf-8")
        rules = []
        in_section = False
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("## "):
                in_section = True
                continue
            if stripped.startswith("rule:") or stripped.startswith("anti:"):
                rules.append(stripped)

        catalog[sf.stem] = "\n".join(rules[:30]) if rules else "(empty)"

    return catalog


def _should_trigger_check(history: List[Dict]) -> bool:
    """是否应该检查收敛。

    条件: 最近 3 轮有至少 2 轮 applied=false 或 accuracy 停滞。
    """
    if len(history) < CONVERGENCE_WINDOW:
        return False

    recent = history[-CONVERGENCE_WINDOW:]
    not_applied = sum(1 for h in recent if not h.get("edits_applied", False))
    if not_applied >= 2:
        return True

    acc = _recent_accuracy(history, CONVERGENCE_WINDOW)
    if len(acc) >= CONVERGENCE_WINDOW and (max(acc) - min(acc)) < CONVERGENCE_EPSILON:
        return True

    return False


def discover(history: List[Dict] = None, force: bool = False) -> dict:
    """EvoSkill 式发现流程：分析辩论轨迹 + 诊断结构性缺失。

    Args:
        history: 准确率历史
        force: 强制触发 (即使未收敛)

    Returns:
        {
          "converged": bool,
          "reason": str,
          "needs_structural_change": bool,
          "analysis": str,
          "proposals": [{"type": "new_skill|new_section|merge_agents", ...}]
        }
    """
    if history is None:
        history = _load_accuracy_history()

    converged, reason = detect_convergence(history)

    if not converged and not force:
        print("Evolve: not converged — {}".format(reason))
        return {
            "converged": False,
            "reason": reason,
            "needs_structural_change": False,
            "analysis": "",
            "proposals": [],
        }

    if force:
        reason = "forced discovery"
        converged = True

    print("Evolve: CONVERGED — {}".format(reason))
    print("Evolve: starting structural discovery...")

    traces = _load_trajectory_samples(max_samples=10)
    print("  Loaded {} samples ({} with traces)".format(
        len(traces), sum(1 for t in traces if t.get("trace_content"))))

    catalog = _load_current_skill_catalog()
    print("  Catalog: {} skills loaded".format(len(catalog)))

    from dotenv import load_dotenv
    load_dotenv(PROJECT_DIR / ".env", override=True)

    from config.default_config import get_config

    config = get_config()
    model = config.get("deep_think_llm", "deepseek-chat")

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    if not api_key:
        return {
            "converged": True, "reason": reason,
            "needs_structural_change": False,
            "analysis": "DEEPSEEK_API_KEY not set",
            "proposals": [], "error": "missing API key",
        }

    import requests

    def _call_deepseek(system: str, user: str) -> dict:
        resp = requests.post(
            "{}/chat/completions".format(base_url.rstrip("/")),
            headers={
                "Authorization": "Bearer {}".format(api_key),
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.1,
                "max_tokens": 3000,
                "response_format": {"type": "json_object"},
            },
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    system_prompt = """You are an Agent Architecture Analyst for a multi-agent stock trading system.

The system has 8 agents in a pipeline:
  Fundamental Analyst → Technical Analyst → Sentiment Analyst → Policy Analyst
  → Bull Researcher ↔ Bear Researcher → Research Manager
  → Trader → Aggressive Risk ↔ Conservative Risk ↔ Neutral Risk → Portfolio Manager

SkillOpt has been optimizing each agent's .skill.md files for several iterations,
but accuracy has plateaued. Your job is to determine if the current 8-agent
ARCHITECTURE itself is insufficient, and if so, what structural change is needed.

## Analysis Rules

Step 1: Examine error patterns across trajectories
- Are there consistent FAILURE MODES that no existing agent can address?
- Is there an information GAP (e.g., no agent checks market breadth or sector rotation)?
- Are any agents consistently OVERRIDDEN by another (suggesting they should be merged)?

Step 2: Diagnose structural gaps
- If ALL errors are about missing domain knowledge → skill editing is enough
- If errors cluster around a capability NONE of the 8 agents have → need new agent/skill
- If two agents always agree or always fight inconclusively → may need restructuring

Step 3: Propose minimal structural changes
- New agent: if a capability gap is clear and specific
- New section: if an existing agent could handle it with a new dedicated section
- Merge: if two agents are redundant
- No change: if SkillOpt can handle it with continued editing

## Output Format

{
  "needs_structural_change": true/false,
  "analysis": "300-char structural diagnosis",
  "proposals": [
    {
      "type": "new_agent|new_skill_section|merge_agents|no_change",
      "name": "proposed agent/section name (e.g. 'sector_rotation_analyst')",
      "reason": "why this is needed",
      "target_agent": "which existing agent to modify (for new_section)",
      "capabilities": ["what this new agent/section should check"],
      "sample_rules": ["sample rule 1", "sample rule 2"]
    }
  ]
}

Only propose structural changes if SkillOpt editing is truly insufficient.
Prefer new_section over new_agent when possible.
Maximum 2 proposals."""

    user_msg = "# Pipeline Accuracy History\n\n"
    user_msg += "Recent runs:\n"
    for h in history[-CONVERGENCE_WINDOW:]:
        user_msg += "- {run}: acc={acc}% (HIT:{hit} AVOID:{avoid} MISS:{miss} STEP:{step})\n".format(
            run=h.get("run_id", "?")[-12:],
            acc=h.get("accuracy", 0),
            hit=h.get("hit", 0), avoid=h.get("avoid", 0),
            miss=h.get("miss", 0), step=h.get("step", 0),
        )

    user_msg += "\n# Current Agent Catalog ({n} agents)\n\n".format(n=len(catalog))
    for skill_name, rules in catalog.items():
        user_msg += "## {}\n{}\n\n".format(skill_name, rules[:600])

    user_msg += "\n# Error Trajectory Samples\n\n"
    for i, t in enumerate(traces):
        user_msg += "### Sample {i}: {code} {name} ({sector})\n".format(
            i=i + 1, code=t["code"], name=t["name"], sector=t["sector"])
        user_msg += "Verdict: {verdict} | Predicted: {rating} | Actual: {chg:+.2f}%\n\n".format(
            verdict=t["verdict"], rating=t["rating"], chg=t["actual_chg"])
        if t.get("trace_content"):
            user_msg += "```\n{}\n```\n\n".format(t["trace_content"][:5000])

    try:
        raw_resp = _call_deepseek(system_prompt, user_msg)
        text = raw_resp["choices"][0]["message"]["content"]
        if not text or text.strip() == "":
            raise ValueError("LLM returned empty content")

        code_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if code_match:
            text = code_match.group(1).strip()

        result = json.loads(text)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {
            "converged": True,
            "reason": reason,
            "needs_structural_change": False,
            "analysis": "Discovery LLM failed: {}".format(str(e)[:200]),
            "proposals": [],
            "error": str(e),
        }

    result["converged"] = converged
    result["reason"] = reason
    result["timestamp"] = datetime.now().isoformat()
    result["convergence_history"] = [h for h in history[-CONVERGENCE_WINDOW:]]

    output_path = OUTPUT_DIR / "discovery.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== Discovery Results ===")
    print("Needs structural change: {}".format(result.get("needs_structural_change", False)))
    print("Analysis: {}".format(result.get("analysis", "N/A")[:200]))
    for i, p in enumerate(result.get("proposals", [])):
        print("  Proposal {}: {} → {}".format(i + 1, p.get("type", ""), p.get("name", "")))
    print("Saved to: {}".format(output_path))

    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Force discovery even if not converged")
    args = parser.parse_args()

    history = _load_accuracy_history()
    print("Pipeline history: {} runs".format(len(history)))
    for h in history:
        print("  {} acc={}% (H:{hit} A:{avoid} M:{miss} S:{step}) applied={app}".format(
            h.get("run_id", "?")[-12:], h.get("accuracy", 0),
            hit=h.get("hit", 0), a=h.get("avoid", 0),
            m=h.get("miss", 0), s=h.get("step", 0),
            app=h.get("edits_applied", False),
        ))

    converged, reason = detect_convergence(history)
    print("\nConvergence: {} — {}".format(converged, reason))

    if converged or args.force:
        result = discover(history, force=args.force)
        print("\nResult: needs_structural_change={}, {} proposals".format(
            result.get("needs_structural_change"), len(result.get("proposals", []))))
        if result.get("error"):
            print("Error: {}".format(result["error"]))
    else:
        print("\nNot converged. Use --force to run discovery anyway.")
