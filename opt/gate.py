"""gate.py — 验证门控：候选 skill 必须在验证集上严格提升才接受

流程:
1. 用新的 skill 文件在验证集日期上重跑 batchanalyze (或 run_batch_date.py)
2. 比较新旧准确率
3. new > old → ACCEPT
4. new <= old → REJECT (写入 rejected_buffer)

rejected_buffer: 记录被拒绝的编辑，下次 optimizer 可参考避免重复走老路。
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))
OPT_DIR = PROJECT_DIR / "opt"
BUFFER_PATH = OPT_DIR / "input" / "rejected_buffer.json"

from opt.utils import atomic_write_text


def load_rejected_buffer() -> list:
    if BUFFER_PATH.exists():
        return json.loads(BUFFER_PATH.read_text(encoding="utf-8"))
    return []


def save_rejected_buffer(buf: list):
    # 注: rejected_buffer 当前未被 optimizer 读取，是历史遗留功能。
    #     gate 仍会写入该文件以保留拒绝记录，但 optimizer 流程不消费它。
    #     如需让 optimizer 参考历史拒绝以避免重复提案，需在 optimizer 中
    #     主动调用 load_rejected_buffer() 注入上下文。
    BUFFER_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(BUFFER_PATH, json.dumps(buf, ensure_ascii=False, indent=2))


def gate(old_accuracy: float, new_accuracy: float,
         analysis: str = "", edits: Optional[list] = None) -> Dict:
    """验证门控：比较新旧准确率。

    Args:
        old_accuracy: 优化前准确率 (%)
        new_accuracy: 优化后准确率 (%)
        analysis: Optimizer 的错误模式分析
        edits: Optimizer 生成的编辑提案

    Returns:
        {
            "accepted": bool,
            "old_accuracy": float,
            "new_accuracy": float,
            "delta": float,
            "action": "ACCEPT" | "REJECT",
            "reason": "..."
        }
    """
    delta = new_accuracy - old_accuracy

    if delta > 0:
        result = {
            "accepted": True,
            "old_accuracy": old_accuracy,
            "new_accuracy": new_accuracy,
            "delta": round(delta, 2),
            "action": "ACCEPT",
            "reason": "Accuracy improved {:.2f}% → {:.2f}% (+{:.2f}%)".format(
                old_accuracy, new_accuracy, delta),
        }
    else:
        reason = "Accuracy {:.2f}% → {:.2f}% ({:+.2f}%) - no improvement".format(
            old_accuracy, new_accuracy, delta)
        if delta == 0:
            reason += "（持平按拒绝处理，避免噪声波动）"
        result = {
            "accepted": False,
            "old_accuracy": old_accuracy,
            "new_accuracy": new_accuracy,
            "delta": round(delta, 2),
            "action": "REJECT",
            "reason": reason,
        }

        # 写入 rejected buffer
        buf = load_rejected_buffer()
        buf.append({
            "timestamp": datetime.now().isoformat(),
            "analysis": analysis,
            "edits": edits or [],
            "old_accuracy": old_accuracy,
            "new_accuracy": new_accuracy,
        })
        # 只保留最近 20 条
        save_rejected_buffer(buf[-20:])
        print("Rejected. Added to buffer (total {} entries)".format(len(buf)))

    # 保存 gate 结果
    (OPT_DIR / "output").mkdir(parents=True, exist_ok=True)
    gate_path = OPT_DIR / "output" / "gate_result.json"
    atomic_write_text(gate_path, json.dumps(result, ensure_ascii=False, indent=2))

    return result


def evaluate_current_accuracy(results_dir: Path, val_dates: list) -> Optional[dict]:
    """在验证集上评估当前 skill 的准确率。

    这里调用 collector.collect() 然后报告准确率。
    注意: 这需要验证集日期的 results/ 已经存在。
    如果没有，需要先跑 run_batch_date.py 对应日期。
    """
    # 简单版本：直接读 results/ 目录中验证集日期的回测结果
    # (round-9, L-opt-2): 删除死变量 hit/avoid/miss/step（从未使用），保留 found
    found = 0

    for date_str in val_dates:
        for f in results_dir.glob("*_{}_analysis.cache.json".format(date_str)):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                # 这里需要实盘数据才能计算，简化版只统计存在的结果数
                found += 1
            except Exception:
                pass

    return {
        "val_dates": val_dates,
        "results_found": found,
        "note": "Full evaluation requires running backtest_today.py on val dates",
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python gate.py <old_accuracy> <new_accuracy>")
        print("Example: python gate.py 64.0 72.5")
        sys.exit(0)

    old_acc = float(sys.argv[1])
    new_acc = float(sys.argv[2])
    result = gate(old_acc, new_acc)
    print(json.dumps(result, ensure_ascii=False, indent=2))
