"""applier.py — 将 Optimizer 输出的编辑应用到 skill 文件

输入: opt/output/edits.json
输出: 修改后的 skills/*.skill.md (通过 Git 管理版本)

编辑类型:
  - add: 在指定 section 末尾添加新规则
  - delete: 删除匹配的规则行
  - replace: 替换匹配的规则行

安全措施:
  - 操作前自动备份 → opt/snapshots/
  - 只编辑 <!-- SKILLOPT-EDITABLE --> 标记之间的区域
  - 校验: 编辑后文件必须包含原 section 标题
"""

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List

PROJECT_DIR = Path(__file__).parent.parent
SKILLS_DIR = PROJECT_DIR / "skills"
OUTPUT_DIR = PROJECT_DIR / "opt" / "output"
SNAPSHOT_DIR = PROJECT_DIR / "opt" / "snapshots"


def backup_skills():
    """备份当前所有 skill 文件到 snapshots/"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = SNAPSHOT_DIR / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    for sf in SKILLS_DIR.glob("*.skill.md"):
        shutil.copy2(sf, backup_dir / sf.name)
    print("Backed up {} skills to {}".format(
        len(list(SKILLS_DIR.glob("*.skill.md"))), backup_dir))
    return backup_dir


def restore_skills(backup_dir) -> int:
    """从 snapshots/ 目录回滚所有 skill 文件。

    Args:
        backup_dir: backup_skills() 返回的 Path 或字符串

    Returns:
        恢复的文件数
    """
    backup_dir = Path(backup_dir)
    if not backup_dir.exists():
        print("Restore failed: backup dir not found: {}".format(backup_dir))
        return 0

    count = 0
    for sf in backup_dir.glob("*.skill.md"):
        target = SKILLS_DIR / sf.name
        shutil.copy2(sf, target)
        count += 1
    print("Restored {} skill files from {}".format(count, backup_dir))
    return count


def parse_skill_sections(content: str) -> Dict[str, List[str]]:
    """解析 skill 文件的 section → 行列表。只返回 SKILLOPT-EDITABLE 区域内的行。

    SKILLOPT-EDITABLE 标记以 toggle 方式工作：第1次遇到开启可编辑区域，
    第2次关闭，第3次再开启…… 成对标记能正确界定边界；单个标记则从该处
    一直延伸到文件末尾。
    """
    sections = {}
    current_section = None
    in_editable = False
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("## "):
            current_section = stripped[3:].strip()
            sections[current_section] = []
            continue
        if "SKILLOPT-EDITABLE" in line:
            # toggle：成对标记的开/关
            in_editable = not in_editable
            continue
        if in_editable:
            if current_section:
                sections[current_section].append(line)
    return sections


def _is_section_editable(content: str, section_name: str) -> bool:
    """检查指定 section 是否在 SKILLOPT-EDITABLE 标记之后（即可编辑）。

    规则：
    - section 内（从 ## header 到下一个 ## 或文件末尾）出现 SKILLOPT-EDITABLE → 可编辑
    - section 内只有其他注释（如"不可更改"）→ 不可编辑
    """
    lines = content.split("\n")
    section_header = "## " + section_name
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped == section_header:
            in_section = True
            continue
        if in_section:
            if stripped.startswith("## "):
                # 进入下一个 section，退出
                break
            if "SKILLOPT-EDITABLE" in line:
                return True
    return False


# 最小长度校验：delete/replace 的 old 文本太短会误删/误改大量行
_MIN_OLD_TEXT_LEN = 10


def _find_section_range(lines: List[str], section_name: str):
    """定位 section 的行范围 [start, end)，返回 (start, end) 或 None。

    start: section header 的下一行
    end:   下一个 ## header 的行号（或文件末尾）
    """
    section_header = "## " + section_name
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if start is None:
            if stripped == section_header:
                start = i + 1
        else:
            # 遇到下一个 ## header 即结束
            if stripped.startswith("## "):
                return (start, i)
    if start is not None:
        return (start, len(lines))
    return None


def apply_edit_to_content(content: str, edit: dict) -> str:
    """对 skill 文件内容应用单条编辑，返回新内容。

    安全校验：
    1. 只允许编辑带 SKILLOPT-EDITABLE 标记的 section（策略铁律等不可改）
    2. delete/replace 的 old 文本必须 ≥ _MIN_OLD_TEXT_LEN 字符，避免误删
    3. delete/replace 只在目标 section 行范围内操作，不会误伤其他 section（含 strategy_iron_rules）
    """
    action = edit["action"]
    section_name = edit["section"]

    # 边界校验：只允许编辑 SKILLOPT-EDITABLE section
    if not _is_section_editable(content, section_name):
        print("  ⚠️ 跳过：section '{}' 未标记 SKILLOPT-EDITABLE，不可编辑".format(section_name))
        return content

    lines = content.split("\n")

    if action == "add":
        new_rule = edit.get("new", "").strip()
        if not new_rule:
            return content
        # 保留原始前缀（rule: 或 anti:），避免 anti 规则被错误转为 rule
        original_prefix = "rule: "
        for prefix in ["rule: ", "anti: "]:
            if new_rule.startswith(prefix):
                new_rule = new_rule[len(prefix):].strip()
                original_prefix = prefix
                break

        # 去重: 如果文件中已存在相同内容，跳过
        normalized_rule = original_prefix + new_rule
        for line in lines:
            if line.strip() == normalized_rule:
                return content

        section_header = "## " + section_name
        target_line = None
        for i, line in enumerate(lines):
            if line.strip() == section_header:
                target_line = i
                break
        if target_line is None:
            return content

        # 找到下一个 ## 或文件末尾
        insert_pos = len(lines)
        for i in range(target_line + 1, len(lines)):
            if lines[i].strip().startswith("## "):
                insert_pos = i
                break

        # 找到最后一个 rule:/anti: 行之后插入
        for i in range(insert_pos - 1, target_line, -1):
            stripped = lines[i].strip()
            if stripped.startswith("rule:") or stripped.startswith("anti:"):
                lines.insert(i + 1, original_prefix + new_rule)
                return "\n".join(lines)

        # 没找到 rule 行，在 section header 后插入
        lines.insert(target_line + 1, original_prefix + new_rule)
        return "\n".join(lines)

    elif action in ("delete", "replace"):
        old_text = edit.get("old", "").strip()
        if len(old_text) < _MIN_OLD_TEXT_LEN:
            print("  ⚠️ 跳过 {}: old 文本过短 ({}<{})，可能误伤多行".format(
                action, len(old_text), _MIN_OLD_TEXT_LEN))
            return content

        # C2: 限定在目标 section 行范围内操作，避免误伤其他 section（如 strategy_iron_rules）
        section_range = _find_section_range(lines, section_name)
        if section_range is None:
            print("  ⚠️ 跳过：未找到 section '{}' 的行范围".format(section_name))
            return content
        sec_start, sec_end = section_range

        new_text = edit.get("new", "").strip() if action == "replace" else ""

        new_lines = []
        for i, line in enumerate(lines):
            # 不在 section 范围内的行原样保留
            if i < sec_start or i >= sec_end:
                new_lines.append(line)
                continue
            stripped = line.strip()
            if old_text and old_text in stripped:
                if action == "delete":
                    continue  # skip this line
                else:  # replace
                    # 保持前缀格式
                    prefix = ""
                    for prefix_candidate in ["rule: ", "anti: "]:
                        if line.strip().startswith(prefix_candidate):
                            prefix = prefix_candidate
                            break
                    new_lines.append(prefix + new_text)
            else:
                new_lines.append(line)
        return "\n".join(new_lines)

    return content


def apply_edits(edits_path: str = None) -> dict:
    """应用编辑提案到 skill 文件。

    Returns:
        {"applied": [...], "skipped": [...], "backup_dir": "..."}
    """
    if edits_path is None:
        # 优先使用 selected > aggregated > raw
        for candidate in ["edits_selected.json", "edits_aggregated.json", "edits.json"]:
            p = OUTPUT_DIR / candidate
            if p.exists():
                edits_path = str(p)
                break

    edits_path = Path(edits_path)
    if not edits_path.exists():
        return {"error": "edits.json not found at {}".format(edits_path)}

    data = json.loads(edits_path.read_text(encoding="utf-8"))
    edits = data.get("edits", [])

    if not edits:
        print("No edits to apply.")
        return {"applied": [], "skipped": [], "backup_dir": None}

    backup_dir = backup_skills()
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    applied = []
    skipped = []

    for edit in edits:
        file_name = edit.get("file", "")
        if not file_name:
            skipped.append({"edit": edit, "reason": "missing file field"})
            continue

        skill_path = SKILLS_DIR / "{}.skill.md".format(file_name)
        if not skill_path.exists():
            skipped.append({"edit": edit, "reason": "file not found: {}".format(skill_path)})
            continue

        old_content = skill_path.read_text(encoding="utf-8")
        new_content = apply_edit_to_content(old_content, edit)

        if new_content == old_content:
            skipped.append({"edit": edit, "reason": "no change detected"})
        else:
            skill_path.write_text(new_content, encoding="utf-8")
            applied.append({"edit": edit, "file": str(skill_path)})
            print("Applied {} to {} section {}".format(
                edit["action"], file_name, edit.get("section", "?")))

    # 保存 applied.json 记录
    record = {
        "timestamp": data.get("meta", {}).get("timestamp", datetime.now().isoformat()),
        "analysis": data.get("analysis", ""),
        "applied": applied,
        "skipped": skipped,
        "backup_dir": str(backup_dir),
    }
    (OUTPUT_DIR / "applied.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nApplied: {} edits, Skipped: {}".format(len(applied), len(skipped)))
    return record


if __name__ == "__main__":
    result = apply_edits()
    if result.get("error"):
        print("Error:", result["error"])
    else:
        for a in result.get("applied", []):
            print("  OK: {} → {}".format(
                a["edit"].get("action"), a["edit"].get("file")))
