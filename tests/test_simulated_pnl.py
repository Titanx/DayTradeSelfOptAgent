"""模拟交易收益逻辑单元测试

覆盖 P1-fix#9 提取的 simulate_trade_return / calc_pnl 两个纯函数:
  - 止盈/止损/收盘平仓三路分支
  - 仓位×收益加权计算
  - 边界条件 (low_pct=None, pos=0, tp+sl 同日触发)
"""
import os
import sys
import unittest
from pathlib import Path

project_dir = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(project_dir))

from scripts.generate_daily_report import simulate_trade_return, calc_pnl

TARGET_GAIN = 1.0
STOP_LOSS = 3.0


class TestSimulateTradeReturn(unittest.TestCase):
    """simulate_trade_return: 模拟单笔交易收益 (TP/SL/Close)"""

    def test_take_profit_only(self):
        """日内 high >= +1%, low 未触及 -3% → 止盈"""
        ret, act = simulate_trade_return(
            high_pct=2.0, low_pct=-1.0, close_pct=1.5,
            target_gain_pct=TARGET_GAIN, stop_loss_pct=STOP_LOSS)
        self.assertEqual(ret, 1.0)
        self.assertEqual(act, "TP")

    def test_stop_loss_only(self):
        """日内 low <= -3%, high 未触及 +1% → 止损"""
        ret, act = simulate_trade_return(
            high_pct=-0.5, low_pct=-4.0, close_pct=-3.5,
            target_gain_pct=TARGET_GAIN, stop_loss_pct=STOP_LOSS)
        self.assertEqual(ret, -3.0)
        self.assertEqual(act, "SL")

    def test_close_forced(self):
        """日内既未触及 +1% 也未触及 -3% → 收盘平仓"""
        ret, act = simulate_trade_return(
            high_pct=0.5, low_pct=-1.5, close_pct=-0.2,
            target_gain_pct=TARGET_GAIN, stop_loss_pct=STOP_LOSS)
        self.assertEqual(ret, -0.2)
        self.assertEqual(act, "Close")

    def test_both_triggers_stop_loss_wins(self):
        """日内 +1.5% 后又 -4% → 保守最坏情形按止损计 (P1-fix#2)"""
        ret, act = simulate_trade_return(
            high_pct=1.5, low_pct=-4.0, close_pct=-2.0,
            target_gain_pct=TARGET_GAIN, stop_loss_pct=STOP_LOSS)
        # low_pct=-4 <= -3 优先判止损
        self.assertEqual(ret, -3.0)
        self.assertEqual(act, "SL")

    def test_low_pct_none_skips_stop_loss(self):
        """D1 模式若 d2_low 缺失 (修复前 Bug) → 不判止损, 走止盈/收盘"""
        ret, act = simulate_trade_return(
            high_pct=2.0, low_pct=None, close_pct=1.5,
            target_gain_pct=TARGET_GAIN, stop_loss_pct=STOP_LOSS)
        self.assertEqual(ret, 1.0)
        self.assertEqual(act, "TP")

    def test_low_pct_none_falls_to_close(self):
        """low_pct=None 且 high < +1% → 收盘平仓"""
        ret, act = simulate_trade_return(
            high_pct=0.5, low_pct=None, close_pct=-0.3,
            target_gain_pct=TARGET_GAIN, stop_loss_pct=STOP_LOSS)
        self.assertEqual(ret, -0.3)
        self.assertEqual(act, "Close")

    def test_boundary_high_equals_target(self):
        """high 恰好 = +1% → 触发止盈 (>=比较)"""
        ret, act = simulate_trade_return(
            high_pct=1.0, low_pct=-0.5, close_pct=0.8,
            target_gain_pct=TARGET_GAIN, stop_loss_pct=STOP_LOSS)
        self.assertEqual(ret, 1.0)
        self.assertEqual(act, "TP")

    def test_boundary_low_equals_stop(self):
        """low 恰好 = -3% → 触发止损 (<=比较)"""
        ret, act = simulate_trade_return(
            high_pct=0.5, low_pct=-3.0, close_pct=-2.5,
            target_gain_pct=TARGET_GAIN, stop_loss_pct=STOP_LOSS)
        self.assertEqual(ret, -3.0)
        self.assertEqual(act, "SL")


class TestCalcPnl(unittest.TestCase):
    """calc_pnl: 多笔交易汇总损益"""

    def test_basic_pnl_calculation(self):
        """3笔交易 (1止盈/1止损/1收盘), 仓位各 10% → 加权收益"""
        trades = [
            {"code": "A", "name": "A", "pos": 0.1, "ret": 1.0},   # +0.1%
            {"code": "B", "name": "B", "pos": 0.1, "ret": -3.0},  # -0.3%
            {"code": "C", "name": "C", "pos": 0.1, "ret": 0.5},   # +0.05%
        ]
        pnl = calc_pnl(trades, initial_capital=1000000,
                       target_gain_pct=TARGET_GAIN, stop_loss_pct=STOP_LOSS)
        # weighted_ret_pct = 1.0*0.1 + (-3.0)*0.1 + 0.5*0.1 = -0.15
        self.assertAlmostEqual(pnl["weighted_ret_pct"], -0.15, places=6)
        self.assertAlmostEqual(pnl["total_pos"], 0.3, places=6)
        self.assertAlmostEqual(pnl["profit"], -1500.0, places=2)  # -0.15% × 100万
        self.assertEqual(pnl["tp_count"], 1)
        self.assertEqual(pnl["sl_count"], 1)
        self.assertEqual(pnl["close_count"], 1)

    def test_all_take_profit(self):
        """全止盈场景"""
        trades = [
            {"code": "A", "name": "A", "pos": 0.2, "ret": 1.0},
            {"code": "B", "name": "B", "pos": 0.2, "ret": 1.0},
        ]
        pnl = calc_pnl(trades, initial_capital=1000000,
                       target_gain_pct=TARGET_GAIN, stop_loss_pct=STOP_LOSS)
        # 1.0*0.2 + 1.0*0.2 = 0.4
        self.assertAlmostEqual(pnl["weighted_ret_pct"], 0.4, places=6)
        self.assertAlmostEqual(pnl["profit"], 4000.0, places=2)  # +0.4% × 100万
        self.assertEqual(pnl["tp_count"], 2)
        self.assertEqual(pnl["sl_count"], 0)
        self.assertEqual(pnl["close_count"], 0)

    def test_empty_trades(self):
        """无交易 → 收益 0, 计数 0"""
        pnl = calc_pnl([], initial_capital=1000000,
                       target_gain_pct=TARGET_GAIN, stop_loss_pct=STOP_LOSS)
        self.assertEqual(pnl["total_pos"], 0)
        self.assertEqual(pnl["weighted_ret_pct"], 0)
        self.assertEqual(pnl["profit"], 0)
        self.assertEqual(pnl["tp_count"], 0)
        self.assertEqual(pnl["sl_count"], 0)
        self.assertEqual(pnl["close_count"], 0)

    def test_zero_position_excluded_from_count(self):
        """仓位为 0 的交易不影响收益但计入交易数"""
        trades = [
            {"code": "A", "name": "A", "pos": 0.0, "ret": 1.0},  # pos=0
            {"code": "B", "name": "B", "pos": 0.1, "ret": 1.0},
        ]
        pnl = calc_pnl(trades, initial_capital=1000000,
                       target_gain_pct=TARGET_GAIN, stop_loss_pct=STOP_LOSS)
        # 1.0*0 + 1.0*0.1 = 0.1
        self.assertAlmostEqual(pnl["weighted_ret_pct"], 0.1, places=6)
        self.assertAlmostEqual(pnl["total_pos"], 0.1, places=6)
        self.assertEqual(pnl["tp_count"], 2)  # ret=1.0 >= TARGET 都算 TP
        self.assertEqual(pnl["close_count"], 0)

    def test_custom_thresholds(self):
        """自定义止盈/止损阈值 (如 +2% / -5%)"""
        trades = [
            {"code": "A", "name": "A", "pos": 0.1, "ret": 2.0},   # TP
            {"code": "B", "name": "B", "pos": 0.1, "ret": -5.0},   # SL
            {"code": "C", "name": "C", "pos": 0.1, "ret": 1.0},    # Close (未达 +2%)
        ]
        pnl = calc_pnl(trades, initial_capital=1000000,
                       target_gain_pct=2.0, stop_loss_pct=5.0)
        self.assertEqual(pnl["tp_count"], 1)
        self.assertEqual(pnl["sl_count"], 1)
        self.assertEqual(pnl["close_count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
