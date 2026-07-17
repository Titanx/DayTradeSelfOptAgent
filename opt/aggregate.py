"""aggregate.py — 聚合去重 Optimizer 的编辑提案

SkillOpt Step 2a: 将 optimizer 输出的多条编辑按 (file, section) 分组，
检测语义相似的规则并合并，避免重复规则、冲突编辑。

策略:
  1. rule-based: 按 (file, section) 分组，检查文本重叠率
  2. LLM fallback: 重叠率高但不完全相同时，调 LLM 合并

输入: opt/output/edits.json
输出: opt/output/edits_aggregated.json
"""

import json
import os
import re
import logging
from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Dict, List

PROJECT_DIR = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_DIR / "opt" / "output"

_logger = logging.getLogger(__name__)


def _text_overlap(a: str, b: str) -> float:
    """计算两段文本的重叠率 (基于字符级 bigram 的 Jaccard)。

    使用 bigram 而非单字符集合，能同时反映字符内容和顺序，避免
    "含相同常用汉字但语义不同" 的误判。涵盖中文字符、英文和数字。
    """
    def _bigrams(s: str) -> set:
        # 保留中文、英文、数字，去除标点和空白
        cleaned = re.sub(r'[^\u4e00-\u9fffA-Za-z0-9]', '', s)
        if len(cleaned) < 2:
            return {cleaned} if cleaned else set()
        return {cleaned[i:i+2] for i in range(len(cleaned) - 1)}

    set_a = _bigrams(a)
    set_b = _bigrams(b)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def _extract_sector_keywords(text: str) -> set:
    """提取板块相关关键词。"""
    sectors = {"光伏", "风电", "AI", "储能", "视觉", "Solar", "Wind", "Energy", "Vision"}
    stocks = {
        "通威", "隆基", "阳光电源", "天合", "迈为",
        "金风", "明阳", "东方电缆", "新强联", "龙源电力",
        "科大讯飞", "寒武纪", "浪潮", "中际旭创", "同花顺",
        "宁德", "亿纬锂能", "国轩", "赣锋", "上海电气",
        "海康", "大华", "德赛", "中科创达", "韦尔",
        "002415", "002236", "603501", "300750", "002460",
    }
    found = set()
    for s in sectors:
        if s in text:
            found.add(s)
    for s in stocks:
        if s in text:
            found.add(s)
    return found


def _merge_edits(edits: List[dict]) -> dict:
    """将多条相似编辑合并为一条。"""
    if len(edits) == 1:
        return edits[0]

    base = dict(edits[0])
    action = base.get("action", "")

    if action == "replace":
        # M6: replace 的 old/new 必须一一对应，不能拼接
        # 合并多条 replace 时：old 取最长（最具体），new 取最长（最完整）
        # 注: 取较长 new 是任意启发式，可能丢失更精准的较短改法；
        #     如需更稳健合并，可改为 LLM 辅助 (_llm_merge) 或人工 review。
        base["old"] = max((e.get("old", "") for e in edits), key=len)
        base["new"] = max((e.get("new", "") for e in edits), key=len)
    else:
        # add: 可以拼接 new（add 无 old）
        merged_new = "；".join(sorted(set(e.get("new", "") for e in edits)))
        if len(merged_new) > 400:
            merged_new = max((e.get("new", "") for e in edits), key=len)
        base["new"] = merged_new

    base["_merged_from"] = len(edits)
    return base


def aggregate(edits_data: dict, use_llm: bool = False) -> dict:
    """聚合编辑提案。

    去重策略:
      1. 同一 (file, section, action)  + 文本重叠率 > 50% → 合并
      2. 同一 (file, section) + 不同 action → 冲突检测，保留 add
      3. 同一 file + delete+add 同一 section → 转为 replace

    Args:
        edits_data: optimizer 的输出 {"edits": [...], "analysis": "..."}
        use_llm: 是否用 LLM 辅助合并 (默认 False，用规则合并)

    Returns:
        聚合后的 edits_data
    """
    edits = edits_data.get("edits", [])
    if len(edits) <= 1:
        result = dict(edits_data)
        result["aggregate"] = {"original_count": len(edits), "merged_count": len(edits), "log": []}
        output_path = OUTPUT_DIR / "edits_aggregated.json"
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print("Aggregate: only {} edit, passed through".format(len(edits)))
        return result

    # Step 1: 按 (file, section) 分组
    groups = defaultdict(list)
    for e in edits:
        key = (e.get("file", ""), e.get("section", ""))
        groups[key].append(e)

    # Step 2: 组内去重
    merged_edits = []
    merge_log = []

    for (file_name, section), group in groups.items():
        if len(group) == 1:
            merged_edits.append(group[0])
            continue

        # 按 action 再次分组
        by_action = defaultdict(list)
        for e in group:
            by_action[e.get("action", "?")].append(e)

        for action, action_group in by_action.items():
            remaining = list(action_group)
            merged = []

            while remaining:
                current = remaining.pop(0)
                similar_indices = []

                for i, other in enumerate(remaining):
                    new_text = current.get("new", "") or current.get("old", "")
                    other_text = other.get("new", "") or other.get("old", "")
                    overlap = _text_overlap(new_text, other_text)
                    kw1 = _extract_sector_keywords(new_text)
                    kw2 = _extract_sector_keywords(other_text)
                    kw_overlap = len(kw1 & kw2) > 0 if (kw1 and kw2) else False

                    # M7/M8: 关键词重叠需同时要求文本相似度≥0.35，避免同板块但意图相反（如买入/卖出）的编辑误合并
                    if overlap > 0.5 or (kw_overlap and overlap > 0.35):
                        similar_indices.append(i)

                if similar_indices:
                    similar = [current] + [remaining[i] for i in reversed(similar_indices)]
                    for i in reversed(similar_indices):
                        remaining.pop(i)
                    merged_edit = _merge_edits(similar)
                    merge_log.append({
                        "action": "merge",
                        "file": file_name,
                        "section": section,
                        "merged_count": len(similar),
                    })
                    merged.append(merged_edit)
                else:
                    merged.append(current)

            merged_edits.extend(merged)

    # Step 3: 冲突检测 — 同一 (file, section) 同时有 delete+add → 转 replace
    conflict_map = defaultdict(lambda: {"add": [], "delete": [], "replace": []})
    for e in merged_edits:
        key = (e.get("file", ""), e.get("section", ""))
        conflict_map[key][e.get("action", "?")].append(e)

    final_edits = []
    for key, actions in conflict_map.items():
        adds = actions["add"]
        deletes = actions["delete"]
        replaces = actions["replace"]

        if adds and deletes:
            merge_log.append({
                "action": "resolve_conflict",
                "file": key[0],
                "section": key[1],
                "detail": "delete+add → replace",
            })
            for d, a in zip(deletes, adds):
                replaces.append({
                    "action": "replace",
                    "file": key[0],
                    "section": key[1],
                    "old": d.get("old", ""),
                    "new": a.get("new", ""),
                    "_resolved_from": "delete+add",
                })
            for d in deletes[len(adds):]:
                final_edits.append(d)
            for a in adds[len(deletes):]:
                final_edits.append(a)
            final_edits.extend(replaces)
        else:
            final_edits.extend(adds + deletes + replaces)

    if use_llm and len(final_edits) > 3:
        final_edits = _llm_merge(final_edits, merge_log)

    result = {
        "analysis": edits_data.get("analysis", ""),
        "edits": final_edits,
        "aggregate": {
            "original_count": len(edits),
            "merged_count": len(final_edits),
            "log": merge_log,
            "timestamp": datetime.now().isoformat(),
        },
        "meta": edits_data.get("meta", {}),
    }

    output_path = OUTPUT_DIR / "edits_aggregated.json"
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Aggregate: {} edits → {} edits".format(len(edits), len(final_edits)))
    for entry in merge_log:
        print("  {} {} @ {}".format(entry["action"], entry.get("file", ""), entry.get("section", "")))
    print("Saved to: {}".format(output_path))

    return result


def _llm_merge(edits: List[dict], merge_log: list) -> List[dict]:
    """LLM 辅助合并：当规则合并后仍然较多时，用 LLM 进一步精简。"""
    try:
        from config.default_config import get_config
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage, HumanMessage

        config = get_config()
        from dotenv import load_dotenv
        load_dotenv(PROJECT_DIR / ".env", override=True)

        provider = config.get("llm_provider", "deepseek")
        model = config.get("quick_think_llm", "deepseek-chat")
        backend = config.get("backend_url")
        temperature = config.get("temperature", 0.1)

        if provider == "deepseek":
            api_key = os.environ.get("DEEPSEEK_API_KEY")
            llm = ChatOpenAI(
                model=model, temperature=temperature, api_key=api_key,
                base_url=backend or "https://api.deepseek.com/v1",
                model_kwargs={"response_format": {"type": "json_object"}},
            )
        else:
            _logger.warning("_llm_merge 仅支持 deepseek provider，当前 provider=%s，跳过 LLM 合并", provider)
            return edits

        sys_prompt = (
            "You are an edit aggregator. Merge semantically identical edits across skill files. "
            "If two edits say essentially the same thing, combine them into one. "
            "Output JSON: {\"edits\": [...], \"merge_log\": [\"merged N edits about ...\"]}"
        )
        user_msg = "Edits:\n" + json.dumps(edits, ensure_ascii=False, indent=2)

        response = llm.invoke([SystemMessage(content=sys_prompt), HumanMessage(content=user_msg)])
        result = json.loads(str(response.content))
        return result.get("edits", edits)
    except Exception:
        return edits


if __name__ == "__main__":
    edits_path = OUTPUT_DIR / "edits.json"
    if not edits_path.exists():
        print("No edits.json found. Run optimizer first.")
        exit(1)

    data = json.loads(edits_path.read_text(encoding="utf-8"))
    result = aggregate(data)
    print("\nFinal edits: {} items".format(len(result.get("edits", []))))
