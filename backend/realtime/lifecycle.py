"""Pure confirmation-state logic for advisory real-time signals.

The worker must supply every gate from closed candles.  This module never
creates an actionable trading recommendation from a score, RSI, or price alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SignalState(str, Enum):
    WATCH = "WATCH"
    READY = "READY"
    ACTIONABLE = "ACTIONABLE"
    INVALIDATED = "INVALIDATED"
    STALE = "STALE"


@dataclass(frozen=True)
class SetupAnalysis:
    """Closed-candle setup levels derived from the same confirmed structure."""

    entry: float
    invalidation: float
    target_one: float
    risk_reward: float
    swing_high: float
    swing_low: float


@dataclass(frozen=True)
class Confirmation:
    symbol: str
    direction: str
    higher_timeframe_aligned: bool
    in_entry_zone: bool
    retest_confirmed: bool
    five_minute_confirmed: bool
    fifteen_minute_qqe_confirmed: bool
    volume_confirmed: bool
    invalidation_hit: bool = False
    data_fresh: bool = True
    analysis: SetupAnalysis | None = None


@dataclass(frozen=True)
class SignalEvaluation:
    state: SignalState
    actionable: bool
    dedup_key: str
    missing_gates: tuple[str, ...]
    analysis: SetupAnalysis | None = None


class SignalLifecycle:
    """Derive a deterministic lifecycle state from explicit confirmations."""

    _required_gates = (
        ("higher_timeframe_aligned", "higher timeframe alignment"),
        ("in_entry_zone", "entry/OTE zone"),
        ("retest_confirmed", "sweep or retest"),
        ("five_minute_confirmed", "5m close confirmation"),
        ("fifteen_minute_qqe_confirmed", "15m QQE confirmation"),
        ("volume_confirmed", "volume confirmation"),
    )

    def evaluate(self, confirmation: Confirmation) -> SignalEvaluation:
        symbol = confirmation.symbol.strip().upper()
        direction = confirmation.direction.strip().upper()
        if not symbol or direction not in {"LONG", "SHORT"}:
            raise ValueError("symbol and direction (LONG or SHORT) are required")

        if not confirmation.data_fresh:
            return self._result(symbol, direction, SignalState.STALE, ("fresh market data",), confirmation.analysis)
        if confirmation.invalidation_hit:
            return self._result(symbol, direction, SignalState.INVALIDATED, ())

        missing = tuple(
            label for field, label in self._required_gates if not getattr(confirmation, field)
        )
        if not missing:
            return self._result(symbol, direction, SignalState.ACTIONABLE, (), confirmation.analysis)
        if confirmation.higher_timeframe_aligned and confirmation.in_entry_zone:
            return self._result(symbol, direction, SignalState.READY, missing)
        return self._result(symbol, direction, SignalState.WATCH, missing)

    @staticmethod
    def _result(
        symbol: str,
        direction: str,
        state: SignalState,
        missing_gates: tuple[str, ...],
        analysis: SetupAnalysis | None = None,
    ) -> SignalEvaluation:
        return SignalEvaluation(
            state=state,
            actionable=state is SignalState.ACTIONABLE,
            dedup_key=f"{symbol}:{direction}:{state.value}",
            missing_gates=missing_gates,
            analysis=analysis,
        )
