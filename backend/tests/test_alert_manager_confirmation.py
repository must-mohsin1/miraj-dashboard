"""Regression tests for confirmation-safe alert dispatch."""

from backend.alerts.manager import is_actionable_trade_plan


def test_high_score_without_trade_decision_is_not_actionable():
    assert is_actionable_trade_plan({"trade_decision": False}) is False
    assert is_actionable_trade_plan({}) is False


def test_explicit_trade_decision_is_required_for_actionable_alert():
    assert is_actionable_trade_plan({"trade_decision": True}) is True
