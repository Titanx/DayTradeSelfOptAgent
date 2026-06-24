"""run_pipeline.py — 一键运行的完整 SkillOpt Pipeline

pipeline 步骤:
  1. collector       → 收集回测数据，输出 rollout.json
  1.5 debate_logger  → 归档辩论轨迹到 opt/trajectories/{run_id}/
  2. optimizer       → 分析错误，输出 edits.json
  3. [review]        → 人工审查编辑提案（可选，默认跳过）
  4. applier         → 应用编辑到 skills/*.skill.md
  5. gate            → (手动) 在验证集重跑后调用 gate.py 比较准确率

用法:
  python opt/run_pipeline.py                        # 全自动模式 (无人工审查)
  python opt/run_pipeline.py --review               # 审查模式 (显示编辑后确认)
  python opt/run_pipeline.py --collect-only          # 只收集数据+归档轨迹
  python opt/run_pipeline.py --status               # 查看状态（含轨迹版本列表）
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from dotenv import load_dotenv
load_dotenv(PROJECT_DIR / ".env", override=True)

from opt.collector import collect, main as collector_main
from opt.optimizer import run_optimizer
from opt.applier import apply_edits
from opt.gate import gate
from opt.debate_logger import save_trajectories, list_versions


def step_collect():
    print("=" * 60)
    print("Step 1: Collect backtest signals → rollout.json")
    print("=" * 60)
    collector_main()


def step_log_trajectories(run_id, edits_data=None):
    """Step 1.5/2.5: 归档辩论轨迹到版本目录。"""
    print("\n" + "=" * 60)
    print("Step 1.5: Archive debate trajectories → opt/trajectories/{}/".format(run_id))
    print("=" * 60)

    rollout_path = PROJECT_DIR / "opt" / "input" / "rollout.json"
    if not rollout_path.exists():
        print("No rollout.json found, skipping trajectory archive.")
        return {"saved": 0, "missed": 0}

    rollout_data = json.loads(rollout_path.read_text(encoding="utf-8"))
    result = save_trajectories(rollout_data, run_id=run_id, edits_data=edits_data)

    if result["missed"] > 0:
        print("Warning: {} stocks have no agent trace (need to re-run analyze)".format(result["missed"]))

    return result


def step_optimize():
    print("\n" + "=" * 60)
    print("Step 2: Optimizer LLM analyzes errors → edits.json")
    print("=" * 60)
    result = run_optimizer()
    if result.get("error"):
        print("Optimizer error: {}".format(result["error"]))
        return None
    return result


def step_review(edit_result):
    """Show proposed edits and ask for confirmation."""
    edits = edit_result.get("edits", [])
    if not edits:
        print("No edits proposed. Pipeline finished.")
        return False

    print("\n" + "=" * 60)
    print("Step 3: Review proposed edits")
    print("=" * 60)
    print("\nAnalysis: {}".format(edit_result.get("analysis", "N/A")))
    print("\nProposed edits:")
    for i, e in enumerate(edits):
        print("  [{i}] {action} {file}.skill.md @ {section}".format(
            i=i + 1,
            action=e.get("action", "?"),
            file=e.get("file", "?"),
            section=e.get("section", "?"),
        ))
        if e.get("old"):
            print("      old: {}".format(e["old"][:80]))
        if e.get("new"):
            print("      new: {}".format(e["new"][:80]))

    answer = input("\nApply these edits? [y/N]: ").strip().lower()
    return answer == "y"


def step_apply():
    print("\n" + "=" * 60)
    print("Step 4: Apply edits to skills/*.skill.md")
    print("=" * 60)
    return apply_edits()


def step_status():
    """Print pipeline status, including trajectory versions."""
    history_path = PROJECT_DIR / "opt" / "output"
    print("\nPipeline Status:")
    print("-" * 40)

    for fname in ["rollout.json", "edits.json", "applied.json", "gate_result.json"]:
        fp = history_path / fname
        if fp.exists():
            data = json.loads(fp.read_text(encoding="utf-8"))
            ts = data.get("timestamp") or data.get("meta", {}).get("timestamp", "?")
            print("  {} - {} ({})".format(fname, ts[:19] if ts else "?", data.get("action", "")))
        else:
            fp_alt = PROJECT_DIR / "opt" / "input" / fname
            if fp_alt.exists():
                print("  {} - EXISTS (input/) ".format(fname))
            else:
                print("  {} - NOT FOUND".format(fname))

    # Snapshots
    snap_dir = PROJECT_DIR / "opt" / "snapshots"
    if snap_dir.exists():
        snaps = sorted(snap_dir.glob("*"))
        print("  snapshots: {} versions".format(len(snaps)))
        if snaps:
            print("    latest: {}".format(snaps[-1].name))

    # Rejected buffer
    buf_path = PROJECT_DIR / "opt" / "input" / "rejected_buffer.json"
    if buf_path.exists():
        buf = json.loads(buf_path.read_text(encoding="utf-8"))
        print("  rejected_buffer: {} entries".format(len(buf)))

    # Trajectory versions
    versions = list_versions()
    if versions:
        print("  trajectories: {} versions".format(len(versions)))
        for v in versions[-5:]:
            print("    {}".format(v["run_id"]))
    else:
        print("  trajectories: NO VERSIONS")


def main():
    parser = argparse.ArgumentParser(description="SkillOpt Pipeline Runner")
    parser.add_argument("--review", action="store_true", help="Interactive review before applying")
    parser.add_argument("--collect-only", action="store_true", help="Only collect data + archive traces")
    parser.add_argument("--status", action="store_true", help="Show pipeline status (incl. trajectories)")
    parser.add_argument("--skip-optimize", action="store_true", help="Skip optimizer (use existing edits.json)")
    args = parser.parse_args()

    if args.status:
        step_status()
        return

    run_id = datetime.now().strftime("v%Y%m%d_%H%M%S")

    print("DayTradeSelfOptAgent SkillOpt Pipeline")
    print("Run ID: {}".format(run_id))
    print("Started: {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    print()

    # Step 1: Collect
    step_collect()

    if args.collect_only:
        step_log_trajectories(run_id)
        print("--collect-only: done. Trajectory version: {}".format(run_id))
        return

    # Step 1.5: Archive debate trajectories
    step_log_trajectories(run_id)

    # Step 2: Optimize
    if not args.skip_optimize:
        edit_result = step_optimize()
        if edit_result is None:
            print("Optimizer failed. Pipeline stopped.")
            return

        # Update trajectory version with edits
        step_log_trajectories(run_id, edits_data=edit_result)

        # Step 3: Review
        if args.review:
            if not step_review(edit_result):
                print("Edits rejected by user. Pipeline stopped.")
                return

    # Step 4: Apply
    apply_result = step_apply()

    print("\n" + "=" * 60)
    print("Pipeline complete!")
    print("Run ID: {}".format(run_id))
    print("Applied: {} edits".format(len(apply_result.get("applied", []))))
    print("Backup: {}".format(apply_result.get("backup_dir", "N/A")))
    print("Trajectories: opt/trajectories/{}/".format(run_id))
    print("=" * 60)


if __name__ == "__main__":
    main()
