"""utils.py — opt 模块共享工具

提供原子写入函数，避免非原子 write_text 在写入中途崩溃导致文件截断损坏，
以及并发写同一文件时固定 .tmp 文件名的 TOCTOU 竞态。

(M-df-12 + M-df-13): optimizer/aggregate/select/gate 共用此实现。
"""

import uuid
from pathlib import Path


def atomic_write_text(path, content):
    """原子写入文本文件（uuid tmp + replace）。

    Args:
        path: 目标文件路径（Path 或 str）
        content: 文本内容（str）

    Notes:
        - 使用 uuid 后缀的临时文件名，避免并发写同一目标时互相覆盖固定 tmp
        - tmp 与目标在同一目录下，确保 replace 在同一文件系统上为原子操作
        - 写入失败时尝试清理 tmp，避免残留
    """
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        raise
