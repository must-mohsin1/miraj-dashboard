"""
Tests for trade_plan module — trade plan generation with RSI 3-entry system.
"""
from mirai_core import config
from mirai_core.confluence import ConfluenceResult, score
from mirai_core.trade_plan import generate_trade_plan


class TestTradePlan:
    """Trade plan generation behaviour."""

    def _high_score_result(self):
        """Create a ConfluenceResult with a high score."""
        data = {
            "weekly_structure_aligned": True,
            "daily_structure_aligned": True,
            "btc_d_aligned": True,
            "weekly_200ma_position": True,
            "usdt_d_favourable": True,
            "bmsb_aligned": True,
            "fear_greed_aligned": True,
            "demand_supply_zone": True,
            "ote_overlap": True,
            "order_block_at_zone": True,
            "fvg_at_zone": True,
            "liquidity_grab_before_ote": True,
            "trend_line_at_zone": True,
            "h4_structure_aligned": True,
            "daily_rsi_confirms": True,
            "h4_rsi_confirms": True,
            "bb_not_squeezing": True,
            "qqe_aligned": True,
            "m15_structure_aligned": True,
            "rsi_divergence_present": True,
            "chart_pattern_confirmed": True,
            "ema_ribbon_aligned": True,
            "volume_confirming": True,
            "retest_confirmed": True,
            "no_fakeout": True,
            "target_2r_available": True,
            "clean_stop_level": True,
            "no_news_risk": True,
        }
        return score(data)

    def test_no_trade_when_below_threshold(self):
        """Score below threshold yields NO TRADE verdict."""
        cr = ConfluenceResult()  # total = 0
        plan = generate_trade_plan(cr)
        assert plan["trade_decision"] is False
        assert "NO TRADE" in plan["verdict"]

    def test_trade_decision_when_high_score(self):
        """High score yields trade decision with plan."""
        cr = self._high_score_result()
        plan = generate_trade_plan(cr, direction="LONG", rsi_current=35.0)
        assert plan["trade_decision"] is True
        assert plan["direction"] == "LONG"

    def test_rsi_entry_system_has_three_entries(self):
        """RSI three-entry system has exactly 3 entries."""
        cr = self._high_score_result()
        plan = generate_trade_plan(cr, direction="LONG", rsi_current=35.0)
        entries = plan["rsi_entry_system"]["entries"]
        assert len(entries) == 3

    def test_rsi_entry_levels_long(self):
        """Long entries have decreasing RSI thresholds."""
        cr = self._high_score_result()
        plan = generate_trade_plan(cr, direction="LONG")
        entries = plan["rsi_entry_system"]["entries"]
        rsis = [e["rsi_target"] for e in entries]
        assert rsis == sorted(rsis, reverse=True)  # decreasing

    def test_rsi_entry_levels_short(self):
        """Short entries have increasing RSI thresholds."""
        cr = self._high_score_result()
        plan = generate_trade_plan(cr, direction="SHORT")
        entries = plan["rsi_entry_system"]["entries"]
        rsis = [e["rsi_target"] for e in entries]
        assert rsis == sorted(rsis)  # increasing

    def test_risk_management_has_rules(self):
        """Risk management section contains key rules."""
        cr = self._high_score_result()
        plan = generate_trade_plan(cr, direction="LONG")
        rules = plan["risk_management"]
        assert len(rules) >= 3

    def test_confirmation_list_included(self):
        """Confirmation list shows which factors were met."""
        cr = self._high_score_result()
        plan = generate_trade_plan(cr, direction="LONG")
        assert len(plan["confirmations_met"]) > 0

    def test_watch_triggers_on_no_trade(self):
        """No-trade verdict includes watch triggers."""
        cr = ConfluenceResult()
        plan = generate_trade_plan(cr)
        assert "watch_triggers" in plan
        assert len(plan["watch_triggers"]) > 0
