"""
记忆系统 — 决策日志持久化

借鉴 TradingAgents 的追加式日志 + 原子更新模式。
存储每次决策和后续实际收益的反思，形成持续学习闭环。
"""

import os
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

ENTRY_SEPARATOR = "<!-- ENTRY_END -->"


class TradingMemoryLog:
    """交易决策记忆日志"""

    def __init__(self, config: dict):
        self.log_path = Path(config.get("memory_log_path", "~/.astock_agent/memory/trading_memory.md"))
        self.log_path = self.log_path.expanduser()
        self.max_entries = config.get("memory_log_max_entries", 50)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def store_decision(self, symbol: str, trade_date: str,
                       decision_text: str) -> None:
        """
        存储决策（立即写入，标记为 pending）

        Args:
            symbol: 股票代码
            trade_date: 分析日期
            decision_text: 决策内容
        """
        # 提取评级（支持 "Strong Buy"/"Buy"/"Hold" 等，遇换行或括号停止）
        rating_match = re.search(r'\*\*Rating\*\*:\s*([A-Za-z ]+?)(?:\s*[\n(]|\s*$)', decision_text)
        rating = rating_match.group(1).strip() if rating_match else "Unknown"

        entry = (
            f"[{trade_date} | {symbol} | {rating} | pending]\n\n"
            f"DECISION:\n{decision_text}\n\n"
            f"{ENTRY_SEPARATOR}\n"
        )

        # 幂等性检查
        if self.log_path.exists():
            existing = self.log_path.read_text(encoding="utf-8")
            if f"[{trade_date} | {symbol}" in existing:
                logger.info(f"已存在同日期同标的的记录，跳过重复写入: {symbol} {trade_date}")
                return

        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(entry)

        logger.info(f"记忆已存储: {symbol} {trade_date} {rating}")

    def get_past_context(self, symbol: str, max_same: int = 5,
                         max_cross: int = 3) -> str:
        """
        获取历史决策上下文（注入 Agent prompt）

        Args:
            symbol: 当前分析标的
            max_same: 同标的决策最多取几条
            max_cross: 跨标的经验教训最多取几条

        Returns:
            格式化后的上下文文本
        """
        if not self.log_path.exists():
            return ""

        content = self.log_path.read_text(encoding="utf-8")
        entries = content.split(ENTRY_SEPARATOR)

        same_entries = []
        cross_entries = []

        for entry in entries:
            entry = entry.strip()
            if not entry:
                continue
            if symbol in entry.split("\n")[0]:
                same_entries.append(entry)
            elif "REFLECTION:" in entry:
                cross_entries.append(entry)

        parts = []

        if same_entries:
            parts.append("## 该标的历史决策\n")
            for e in same_entries[-max_same:]:
                parts.append(e.strip() + "\n")

        if cross_entries and max_cross > 0:
            parts.append("## 跨标的历史经验\n")
            for e in cross_entries[-max_cross:]:
                # 只取反思部分
                reflection_match = re.search(
                    r'REFLECTION:(.*?)(?=\[|<!--|\Z)', e, re.DOTALL
                )
                if reflection_match:
                    parts.append(f"- {reflection_match.group(1).strip()[:200]}\n")

        return "\n".join(parts) if parts else ""

    def get_pending_entries(self) -> List[Tuple[str, str, str]]:
        """
        获取所有未结算的 pending 条目

        Returns:
            [(date, symbol, entry_text), ...]
        """
        if not self.log_path.exists():
            return []

        content = self.log_path.read_text(encoding="utf-8")
        entries = content.split(ENTRY_SEPARATOR)
        pending = []

        for entry in entries:
            entry = entry.strip()
            if not entry or "pending" not in entry[:200]:
                continue
            match = re.match(r'\[(\S+)\s*\|\s*(\S+)', entry)
            if match:
                pending.append((match.group(1), match.group(2), entry))

        return pending

    def batch_update_with_outcomes(self,
                                    outcomes: List[Tuple[str, str, str]]) -> None:
        """
        批量更新 pending 条目为已结算（含收益和反思）

        Args:
            outcomes: [(date, symbol, reflection_text), ...]
        """
        if not self.log_path.exists():
            return

        content = self.log_path.read_text(encoding="utf-8")
        entries = content.split(ENTRY_SEPARATOR)
        updated = []

        for entry in entries:
            entry = entry.strip()
            if not entry:
                updated.append(entry)
                continue

            found = False
            for outcome_date, outcome_symbol, reflection in outcomes:
                if f"[{outcome_date} | {outcome_symbol}" in entry:
                    # 替换 pending 为实际数据
                    prefix = entry.split("\n")[0]
                    new_prefix = prefix.replace("pending", "resolved")
                    # (round-9, L-core-10): 仅替换首处 prefix，避免多匹配误改
                    entry = entry.replace(prefix, new_prefix, 1)
                    entry += f"\n\nREFLECTION:\n{reflection}\n"
                    found = True
                    break

            # (round-9, L-core-1): 两个分支都 append entry，三元冗余 → 简化
            updated.append(entry)

        # 原子写入（临时文件 + 替换）
        tmp_path = self.log_path.with_suffix(".tmp")
        tmp_path.write_text(ENTRY_SEPARATOR.join(updated), encoding="utf-8")
        tmp_path.replace(self.log_path)

        # 旋转（删除最旧的已结算条目）
        self._apply_rotation()

    def _apply_rotation(self) -> None:
        """旋转日志，保持总条目数不超过上限"""
        if not self.log_path.exists():
            return

        content = self.log_path.read_text(encoding="utf-8")
        entries = content.split(ENTRY_SEPARATOR)
        entries = [e.strip() for e in entries if e.strip()]

        # pending 条目不删除
        pending = [e for e in entries if "pending" in e[:200]]
        resolved = [e for e in entries if "pending" not in e[:200]]

        if len(resolved) <= self.max_entries:
            return

        # 保留最新的 max_entries 条已结算
        resolved_keep = resolved[-self.max_entries:]
        resolved_keep_set = set(resolved_keep)

        # (round-9, M-core-3): 保持原始时间顺序合并，避免重排
        # 原实现 pending + resolved 会把 pending 前置、resolved 后置，
        # 而 get_past_context 用 same_entries[-max_same:] 取最新条目，
        # 导致最新 pending 决策在 resolved 数量 >= max_same 时被排除出上下文。
        all_entries = [
            e for e in entries
            if (e in resolved_keep_set) or ("pending" in e[:200])
        ]
        tmp_path = self.log_path.with_suffix(".tmp")
        tmp_path.write_text(ENTRY_SEPARATOR.join(all_entries), encoding="utf-8")
        tmp_path.replace(self.log_path)
