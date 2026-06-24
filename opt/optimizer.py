"""optimizer.py — 调用 Optimizer LLM 分析回测错误，生成有界编辑提案

输入: opt/input/rollout.json (由 collector.py 生成)
输出: opt/output/edits.json (结构化编辑提案)

Optimizer LLM: 使用与主系统相同的 langchain_openai.ChatOpenAI + DeepSeek V4 Pro，
  与 trading_graph.py 中 _create_llm("deep") 完全一致的调用方式。
"""

import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from dotenv import load_dotenv
load_dotenv(PROJECT_DIR / ".env", override=True)

INPUT_DIR = PROJECT_DIR / "opt" / "input"
OUTPUT_DIR = PROJECT_DIR / "opt" / "output"
SKILLS_DIR = PROJECT_DIR / "skills"


def _create_optimizer_llm():
    """创建 Optimizer LLM 客户端，与主系统 _create_llm("deep") 完全一致。"""
    from config.default_config import get_config
    from langchain_openai import ChatOpenAI

    config = get_config()
    provider = config.get("llm_provider", "deepseek")
    model = config.get("deep_think_llm", "deepseek-chat")
    backend = config.get("backend_url")
    temperature = config.get("temperature", 0.1)

    if provider == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=api_key,
            base_url=backend or "https://api.deepseek.com/v1",
            model_kwargs={"response_format": {"type": "json_object"}},
        )
    elif provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=api_key,
            base_url=backend,
            model_kwargs={"response_format": {"type": "json_object"}},
        )
    elif provider == "qwen":
        api_key = os.environ.get("DASHSCOPE_API_KEY")
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=api_key,
            base_url=backend or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            model_kwargs={"response_format": {"type": "json_object"}},
        )
    elif provider == "ollama":
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            base_url=backend or "http://localhost:11434/v1",
            api_key="ollama",
            model_kwargs={"response_format": {"type": "json_object"}},
        )
    else:
        api_key = os.environ.get("OPENAI_API_KEY")
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=api_key,
            base_url=backend,
            model_kwargs={"response_format": {"type": "json_object"}},
        )


def _extract_json(text: str) -> dict:
    """从 LLM 响应中提取 JSON，支持 markdown 代码块包裹。"""
    text = text.strip()
    code_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
    if code_match:
        text = code_match.group(1).strip()
    return json.loads(text)


def load_optimizer_prompt():
    prompt_file = Path(__file__).parent / "optimizer_prompt.md"
    return prompt_file.read_text(encoding="utf-8")


def build_user_message(rollout_data: dict) -> str:
    """构建给 Optimizer 的用户消息，包含回测摘要和当前 skills。"""
    summary = rollout_data.get("group_summary", {})
    overall = summary.get("overall", {})

    msg = "# Backtest Summary\n\n"
    msg += "Overall: {hit} HIT, {avoid} AVOID, {miss} MISS, {step} STEP ".format(**overall)
    msg += "(accuracy: {acc}%)\n\n".format(acc=overall.get("accuracy", 0))

    msg += "## By Sector\n\n"
    for sector, s in summary.get("by_sector", {}).items():
        msg += "- {sec}: {hit}H/{avoid}A/{miss}M/{step}S (acc {acc}%)\n".format(
            sec=sector, hit=s["hit"], avoid=s["avoid"],
            miss=s["miss"], step=s["step"], acc=s["accuracy"]
        )

    miss_cases = summary.get("by_error_type", {}).get("MISS", [])
    if miss_cases:
        msg += "\n## MISS Cases (Buy but fail)\n\n"
        for c in miss_cases[:5]:
            msg += "- {date} {stock}({sector}): pred {rating} {conf:.0%}, actual {chg:+.2f}%\n".format(
                date=c["date"], stock=c["stock"], sector=c["sector"],
                rating=c["rating"], conf=c["confidence"], chg=c["actual_chg"]
            )

    step_cases = summary.get("by_error_type", {}).get("STEP", [])
    if step_cases:
        msg += "\n## STEP Cases (Hold but up >=1%)\n\n"
        for c in step_cases[:10]:
            msg += "- {date} {stock}({sector}): pred {rating} {conf:.0%}, actual {chg:+.2f}%\n".format(
                date=c["date"], stock=c["stock"], sector=c["sector"],
                rating=c["rating"], conf=c["confidence"], chg=c["actual_chg"]
            )

    msg += "\n## Current Skill Files (SKILLOPT-EDITABLE regions only)\n\n"
    skill_files = rollout_data.get("skill_files", {})
    for skill_name in ["bull_researcher", "bear_researcher", "portfolio_manager",
                       "trader", "research_manager"]:
        content = skill_files.get(skill_name, "")
        if content:
            msg += "### {}\n```markdown\n{}\n```\n\n".format(skill_name, content[:3000])

    return msg


def run_optimizer(rollout_path: str = None) -> dict:
    """Run the Optimizer LLM and return edit proposals.

    Args:
        rollout_path: Path to rollout.json. Default: opt/input/rollout.json

    Returns:
        {"analysis": "...", "edits": [...], "meta": {...}}
    """
    if rollout_path is None:
        rollout_path = INPUT_DIR / "rollout.json"

    rollout_path = Path(rollout_path)
    if not rollout_path.exists():
        return {"error": "rollout.json not found at {}".format(rollout_path), "edits": []}

    rollout_data = json.loads(rollout_path.read_text(encoding="utf-8"))

    system_prompt = load_optimizer_prompt()
    user_message = build_user_message(rollout_data)

    from langchain_core.messages import SystemMessage, HumanMessage

    try:
        llm = _create_optimizer_llm()
        response = llm.invoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_message),
        ])
    except Exception as e:
        return {"error": "Optimizer LLM call failed: {}".format(e), "edits": []}

    try:
        result = _extract_json(str(response.content))
    except (json.JSONDecodeError, ValueError) as e:
        raw = str(response.content)[:500] if response.content else "(empty)"
        return {"error": "Optimizer returned invalid JSON: {}".format(raw), "edits": []}

    result["meta"] = {
        "timestamp": datetime.now().isoformat(),
        "rollout_date_range": rollout_data.get("date_range", "?"),
        "total_results": len(rollout_data.get("rollout_results", [])),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "edits.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Optimizer output saved to: {}".format(output_path))
    if result.get("analysis"):
        print("Analysis: {}".format(result["analysis"][:120]))
    print("Edits: {} proposals".format(len(result.get("edits", []))))

    return result


if __name__ == "__main__":
    result = run_optimizer()
    print(json.dumps(result, ensure_ascii=False, indent=2))
