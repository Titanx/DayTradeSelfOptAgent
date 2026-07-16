"""
Markdown 格式化工具

统一将 dict / DataFrame / list 转为人类可读的 Markdown 文本，
替代项目中所有 json.dumps() 输出。
"""

from datetime import datetime
from typing import Any


def to_markdown(data: Any, title: str = "") -> str:
    """
    将任意数据递归转为 Markdown。

    - dict   → 表格（key / value）
    - dict of dicts → 嵌套表格（section > table）
    - list of dicts → 表格（表头为 keys）
    - DataFrame → 表格
    - str/list/int/float → 原样
    """
    if data is None:
        return f"# {title}\n\n*无数据*\n" if title else "*无数据*"

    lines = []
    if title:
        lines.append(f"# {title}")
        lines.append(f"\n> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")

    lines.append(_render_value(data, level=1))
    return "\n".join(lines)


def _render_value(data: Any, level: int = 1) -> str:
    """递归渲染任意值为 MD"""
    if data is None:
        return "*无数据*"

    # DataFrame / Series
    try:
        import pandas as pd
        import numpy as np
        if isinstance(data, pd.DataFrame):
            return _df_to_table(data)
        if isinstance(data, pd.Series):
            return _df_to_table(data.to_frame(name="value"))
    except ImportError:
        pass

    # list
    if isinstance(data, list):
        if not data:
            return "*空列表*"
        # 检查所有元素是否都是 dict（避免异构列表崩溃）
        if all(isinstance(item, dict) for item in data):
            return _records_to_table(data)
        # 普通列表（含异构）
        rows = []
        for i, item in enumerate(data, 1):
            if isinstance(item, dict):
                rows.append(_render_value(item, level + 1))
            else:
                rows.append(f"{i}. {str(item)[:200]}")
        return "\n".join(rows)

    # dict
    if isinstance(data, dict):
        return _dict_to_sections(data, level)

    # 标量
    return str(data)


def _dict_to_sections(d: dict, level: int = 1) -> str:
    """Dict 转 MD：简单 key-value 用表格，嵌套 dict 用段落"""
    simple = {}
    nested = {}

    for k, v in d.items():
        if isinstance(v, (dict, list)):
            nested[k] = v
        else:
            simple[k] = v

    parts = []

    # 简单字段 → 表格
    if simple:
        rows = ["| 指标 | 数值 |", "|------|------|"]
        for k, v in simple.items():
            vs = _format_scalar(v)
            rows.append(f"| {k} | {vs} |")
        parts.append("\n".join(rows))

    # 嵌套字段 → 各自段落
    for k, v in nested.items():
        heading = "#" * min(level + 1, 5)
        parts.append(f"\n{heading} {k}")
        parts.append(_render_value(v, level + 1))

    return "\n".join(parts)


def _records_to_table(records: list) -> str:
    """list[dict] → Markdown 表格

    合并所有记录的 keys 作为表头（避免异构 dict 丢失字段）。
    """
    if not records:
        return "*空*"
    # 收集所有记录中出现过的 key（保持首次出现顺序）
    keys = []
    seen = set()
    for rec in records:
        for k in rec.keys():
            if k not in seen:
                seen.add(k)
                keys.append(k)
    rows = []
    rows.append("| " + " | ".join(str(k) for k in keys) + " |")
    rows.append("|" + "|".join("------" for _ in keys) + "|")
    for rec in records:
        cells = [_format_scalar(rec.get(k, "")) for k in keys]
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def _df_to_table(df) -> str:
    """DataFrame → Markdown 表格"""
    import numpy as np
    cols = list(df.columns)
    rows = []

    rows.append("| " + " | ".join(str(c) for c in cols) + " |")
    rows.append("|" + "|".join("------" for _ in cols) + "|")

    for _, row in df.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            if v is None or (isinstance(v, float) and np.isnan(v)):
                cells.append("-")
            elif isinstance(v, float):
                cells.append(f"{v:.2f}")
            else:
                cells.append(str(v)[:80])
        rows.append("| " + " | ".join(cells) + " |")
    return "\n".join(rows)


def _format_scalar(v: Any) -> str:
    """标量格式化为字符串"""
    if v is None:
        return "-"
    if isinstance(v, float):
        if abs(v) >= 1e8:
            return f"{v:.2e}"
        if abs(v) >= 100:
            return f"{v:,.2f}"
        return f"{v:.2f}"
    if isinstance(v, bool):
        return "✓" if v else "✗"
    s = str(v)
    return s[:200]
