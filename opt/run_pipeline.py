"""run_pipeline.py — 一键运行的完整 SkillOpt Pipeline

pipeline 步骤:
  1. collector       → 收集回测数据，输出 rollout.json
  1.5 debate_logger  → 归档辩论轨迹到 opt/trajectories/{run_id}/
  2. optimizer       → 分析错误，输出 edits.json
  2a. aggregate      → 合并去重相似编辑，输出 edits_aggregated.json
  2b. select         → 多维评分挑选 top-k，输出 edits_selected.json
  3. [review]        → 人工审查编辑提案（可选，默认跳过）
  4. applier         → 应用编辑到 skills/*.skill.md
  5. gate            → (手动) 在验证集重跑后调用 gate.py 比较准确率
  6. evolve          → 收敛检测: 当 SkillOpt 多轮无法提升时，触发结构性发现

用法:
  python opt/run_pipeline.py                        # 全自动模式 (无人工审查)
  python opt/run_pipeline.py --review               # 审查模式 (显示编辑后确认)
  python opt/run_pipeline.py --collect-only          # 只收集数据+归档轨迹
  python opt/run_pipeline.py --evolve               # 强制运行结构性发现
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
from opt.aggregate import aggregate
from opt.select import select as select_edits
from opt.applier import apply_edits, restore_skills
from opt.gate import gate
from opt.debate_logger import save_trajectories, list_versions
from opt.evolve import discover, record_run, detect_convergence, _load_accuracy_history

# 用于记录上一轮 apply 时的准确率，供下一轮 gate 对比
LAST_RUN_INFO_PATH = PROJECT_DIR / "opt" / "output" / "last_run.json"


def _load_last_run() -> dict:
    """加载上一轮 pipeline 的 apply 信息（accuracy + backup_dir）"""
    if LAST_RUN_INFO_PATH.exists():
        try:
            return json.loads(LAST_RUN_INFO_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_last_run(info: dict):
    LAST_RUN_INFO_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN_INFO_PATH.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")


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


def step_aggregate(edit_result):
    """Step 2a: 合并去重相似编辑。"""
    edits = edit_result.get("edits", [])
    if len(edits) <= 1:
        print("\nStep 2a: Aggregate — only {} edit, skipped".format(len(edits)))
        return edit_result

    print("\n" + "=" * 60)
    print("Step 2a: Aggregate — deduplicate similar edits")
    print("=" * 60)
    return aggregate(edit_result)


def step_select(edit_result):
    """Step 2b: 多维评分选 top-k。"""
    edits = edit_result.get("edits", [])
    if len(edits) <= 3:
        print("\nStep 2b: Select — only {} edits, skipped".format(len(edits)))
        return edit_result

    print("\n" + "=" * 60)
    print("Step 2b: Select — score & pick top-k")
    print("=" * 60)
    return select_edits(edit_result, top_k=3)


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

    for fname in ["rollout.json", "edits.json", "edits_aggregated.json",
                   "edits_selected.json", "applied.json", "gate_result.json",
                   "discovery.json"]:
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

    # Evolution status
    history = _load_accuracy_history()
    if history:
        print("  pipeline_history: {} runs".format(len(history)))
        converged, reason = detect_convergence(history)
        print("  convergence: {} — {}".format("CONVERGED" if converged else "improving", reason))
        if converged:
            discovery_path = PROJECT_DIR / "opt" / "output" / "discovery.json"
            if discovery_path.exists():
                disc = json.loads(discovery_path.read_text(encoding="utf-8"))
                print("  discovery: {} proposals".format(len(disc.get("proposals", []))))
            else:
                print("  discovery: NOT YET RUN")
    else:
        print("  pipeline_history: NO DATA")


def main():
    parser = argparse.ArgumentParser(description="SkillOpt Pipeline Runner")
    parser.add_argument("--review", action="store_true", help="Interactive review before applying")
    parser.add_argument("--collect-only", action="store_true", help="Only collect data + archive traces")
    parser.add_argument("--status", action="store_true", help="Show pipeline status (incl. trajectories)")
    parser.add_argument("--skip-optimize", action="store_true", help="Skip optimizer (use existing edits.json)")
    parser.add_argument("--force-apply", action="store_true", help="Force apply edits even when accuracy >= threshold")
    parser.add_argument("--evolve", action="store_true", help="Force structural discovery (EvoSkill loop) even if not converged")
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

    # load rollout for tracking
    rollout_path = PROJECT_DIR / "opt" / "input" / "rollout.json"
    rollout_data = {}
    if rollout_path.exists():
        rollout_data = json.loads(rollout_path.read_text(encoding="utf-8"))

    # ============================================================
    # Gate 回滚检查：对比上一轮 apply 前的 accuracy 与本轮 collect 得到的 accuracy
    # 如果劣化（new < old），回滚到上一轮的 backup
    # ============================================================
    last_run = _load_last_run()
    if last_run and last_run.get("applied") and last_run.get("backup_dir"):
        old_acc = last_run.get("accuracy", 0)
        new_acc = rollout_data.get("group_summary", {}).get("overall", {}).get("accuracy", 0)
        if old_acc > 0 and new_acc > 0:
            gate_result = gate(old_acc, new_acc,
                               analysis="Post-apply regression check",
                               edits=last_run.get("edits", []))
            print("\nStep 1.5: Gate regression check")
            print("  old_accuracy: {:.1f}%  new_accuracy: {:.1f}%  delta: {:+.1f}%".format(
                old_acc, new_acc, new_acc - old_acc))
            if not gate_result["accepted"]:
                print("  ⚠️ Accuracy regressed after last apply. Rolling back skill files...")
                restored = restore_skills(last_run["backup_dir"])
                print("  ✅ Rolled back {} skill files".format(restored))
                # 清除 last_run 避免重复回滚
                _save_last_run({})
                record_run(run_id, rollout_data, applied=False)
                print("Pipeline stopped after rollback. Please re-run to optimize from restored baseline.")
                return
            else:
                print("  ✅ Accuracy improved or stable. Keeping applied edits.")

    if args.collect_only:
        step_log_trajectories(run_id)
        record_run(run_id, rollout_data)
        print("--collect-only: done. Trajectory version: {}".format(run_id))
        return

    # Step 1.5: Archive debate trajectories
    step_log_trajectories(run_id)

    applied_edits = False
    edit_result = {}

    # Step 2: Optimize
    if not args.skip_optimize:
        edit_result = step_optimize()
        if edit_result is None:
            print("Optimizer failed. Pipeline stopped.")
            record_run(run_id, rollout_data, edit_result, applied=False)
            return

        # Step 2a: Aggregate
        edit_result = step_aggregate(edit_result)

        # Step 2b: Select top-k
        edit_result = step_select(edit_result)

        # Update trajectory version with edits
        step_log_trajectories(run_id, edits_data=edit_result)

        # Step 3: Review
        if args.review:
            if not step_review(edit_result):
                print("Edits rejected by user. Pipeline stopped.")
                record_run(run_id, rollout_data, edit_result, applied=False)
                return

    # Step 3.5: Accuracy threshold guard
    # 当准确率 >= 阈值时，保守策略已在回调日表现良好，
    # 自动应用编辑可能破坏这种优势 → 仅收集数据，跳过 apply
    ACCURACY_THRESHOLD = 70.0
    current_accuracy = rollout_data.get("group_summary", {}).get("overall", {}).get("accuracy", 0)
    history = _load_accuracy_history()
    converge_status, converge_reason = detect_convergence(history)

    if current_accuracy >= ACCURACY_THRESHOLD and not args.force_apply:
        print("\n" + "=" * 60)
        print("Step 3.5: Accuracy gate — {:.1f}% >= {:.0f}% threshold".format(
            current_accuracy, ACCURACY_THRESHOLD))
        print("=" * 60)
        print("Current accuracy is strong. Applying edits at this level may")
        print("degrade conservative behavior that works well in correction days.")
        print("→ Skipping auto-apply. Use --force-apply to override.")
        print("→ Trajectories archived at opt/trajectories/{}/".format(run_id))
        print("→ Re-run pipeline when accuracy drops below {:.0f}%".format(ACCURACY_THRESHOLD))
        record_run(run_id, rollout_data, edit_result, applied=False)
        return

    if current_accuracy >= ACCURACY_THRESHOLD and args.force_apply:
        print("\n⚠️  Accuracy {:.1f}% >= {:.0f}% — --force-apply overriding gate".format(
            current_accuracy, ACCURACY_THRESHOLD))

    # Step 4: Apply
    apply_result = step_apply()
    applied_edits = len(apply_result.get("applied", [])) > 0

    # 保存本轮 apply 信息，供下一轮 pipeline 的 gate 回滚检查
    if applied_edits:
        _save_last_run({
            "run_id": run_id,
            "accuracy": current_accuracy,
            "backup_dir": str(apply_result.get("backup_dir", "")),
            "edits": [a.get("edit", {}) for a in apply_result.get("applied", [])],
            "applied": True,
            "timestamp": datetime.now().isoformat(),
        })

    # Record this run
    record_run(run_id, rollout_data, edit_result, applied=applied_edits)

    print("\n" + "=" * 60)
    print("Pipeline complete!")
    print("Run ID: {}".format(run_id))
    print("Applied: {} edits".format(len(apply_result.get("applied", []))))
    print("Backup: {}".format(apply_result.get("backup_dir", "N/A")))
    print("Trajectories: opt/trajectories/{}/".format(run_id))
    print("=" * 60)

    # Step 5 (auto): 收敛检测 + EvoSkill 式发现
    history = _load_accuracy_history()
    converged, reason = detect_convergence(history)
    print("\nConvergence check: {} — {}".format("CONVERGED" if converged else "OK", reason))

    if converged or args.evolve:
        print("\n" + "=" * 60)
        print("Step 5: EvoSkill Discovery — structural analysis")
        print("=" * 60)
        discovery = discover(history, force=args.evolve)
        if discovery.get("needs_structural_change"):
            print("\n⚠️  STRUCTURAL CHANGE PROPOSED!")
            for p in discovery.get("proposals", []):
                print("  - {}: {}".format(p.get("type", ""), p.get("name", "")))
            print("Review discovery.json before applying.")
    else:
        print("(EvoSkill loop not triggered — accuracy still improving)")


if __name__ == "__main__":
    main()
