"""SQLAlchemy ORM models for the crypto analysis application."""

import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.types import JSON

from backend.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(128), unique=True, nullable=False, index=True)
    hashed_password = Column(String(256), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    analyses = relationship("Analysis", back_populates="user", cascade="all, delete-orphan")
    watchlist_pairs = relationship("WatchlistPair", back_populates="user", cascade="all, delete-orphan")
    pair_settings = relationship("PairSetting", back_populates="user", cascade="all, delete-orphan")
    alert_channels = relationship("AlertChannel", back_populates="user", cascade="all, delete-orphan")
    alert_histories = relationship("AlertHistory", back_populates="user", cascade="all, delete-orphan")
    price_alerts = relationship("PriceAlert", back_populates="user", cascade="all, delete-orphan")
    exchange_keys = relationship("ExchangeKey", back_populates="user", cascade="all, delete-orphan")
    portfolio_balances = relationship("PortfolioBalance", back_populates="user", cascade="all, delete-orphan")
    portfolio_positions = relationship("PortfolioPosition", back_populates="user", cascade="all, delete-orphan")
    portfolio_trades = relationship("PortfolioTrade", back_populates="user", cascade="all, delete-orphan")
    portfolio_snapshots = relationship("PortfolioSnapshot", back_populates="user", cascade="all, delete-orphan")
    futures_account_snapshots = relationship("FuturesAccountSnapshot", back_populates="user", cascade="all, delete-orphan")
    exchange_sync_states = relationship("ExchangeSyncState", back_populates="user", cascade="all, delete-orphan")
    capital_flow_ledger = relationship("CapitalFlowLedger", back_populates="user", cascade="all, delete-orphan")
    dca_shadow_user_kill_switches = relationship("DcaShadowUserKillSwitch", back_populates="user", cascade="all, delete-orphan")
    dca_shadow_symbol_kill_switches = relationship("DcaShadowSymbolKillSwitch", back_populates="user", cascade="all, delete-orphan")
    dca_shadow_decision_history = relationship("DcaShadowDecisionHistory", back_populates="user", cascade="all, delete-orphan")
    position_history = relationship("PositionHistory", back_populates="user", cascade="all, delete-orphan")
    order_history = relationship("OrderHistory", back_populates="user", cascade="all, delete-orphan")
    journal_entries = relationship("TradeJournalEntry", back_populates="user", cascade="all, delete-orphan")


class AlertChannel(Base):
    """Per-user Telegram, Discord, email, or signed-webhook configuration."""

    __tablename__ = "alert_channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    channel_type = Column(String(20), nullable=False)  # telegram / discord / email / webhook
    config = Column(Text, nullable=True)                # Channel-specific JSON configuration
    enabled = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="alert_channels")


class AlertHistory(Base):
    """Log of every sent (or failed) alert for dedup and audit."""

    __tablename__ = "alert_histories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    pair = Column(String(20), nullable=False, index=True)
    channel = Column(String(20), nullable=False)   # telegram / discord / email / webhook
    score = Column(Float, nullable=True)
    direction = Column(String(10), nullable=True)  # LONG / SHORT
    message = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="sent")  # sent, failed
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="alert_histories")


class SignalWebhookDelivery(Base):
    """Committed outbox row for a signed scan-signal webhook."""

    __tablename__ = "signal_webhook_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "channel_id",
            "delivery_id",
            "config_fingerprint",
            name="uq_signal_webhook_channel_delivery",
        ),
        Index(
            "ix_signal_webhook_deliveries_status_due",
            "status",
            "next_attempt_at",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel_id = Column(
        Integer,
        ForeignKey("alert_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pair = Column(String(20), nullable=False, index=True)
    direction = Column(String(10), nullable=False)
    score = Column(Float, nullable=True)
    delivery_id = Column(String(36), nullable=False)
    payload = Column(Text, nullable=False)
    config_fingerprint = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime, nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    last_status_code = Column(Integer, nullable=True)
    last_error = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    sent_at = Column(DateTime, nullable=True)


class Analysis(Base):
    __tablename__ = "analyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    pair = Column(String(20), nullable=False, index=True)  # e.g. "BTCUSDT"
    analysis_type = Column(String(64), nullable=False)       # e.g. "trend", "rsi", "ma"
    parameters = Column(Text, nullable=True)                 # JSON blob of parameters
    result = Column(Text, nullable=True)                     # JSON blob of result data
    score = Column(Float, nullable=True)                     # cached score extracted from result JSON
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="analyses")


class WatchlistPair(Base):
    __tablename__ = "watchlist_pairs"
    __table_args__ = (
        UniqueConstraint("user_id", "pair", name="uq_user_pair"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    pair = Column(String(20), nullable=False)  # e.g. "BTCUSDT"
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="watchlist_pairs")


class PairSetting(Base):
    __tablename__ = "pair_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    pair = Column(String(20), nullable=False)  # e.g. "BTCUSDT"
    settings = Column(Text, nullable=True)     # JSON blob of settings
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="pair_settings")


class ScanRun(Base):
    """Track each scheduled scan execution cycle."""

    __tablename__ = "scan_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    ended_at = Column(DateTime, nullable=True)
    status = Column(String(20), nullable=False, default="running")  # running, completed, failed
    pair_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)


class PriceAlert(Base):
    """User-defined price alert — notify when a symbol hits a target/stop level."""

    __tablename__ = "price_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    alert_type = Column(String(20), nullable=False, default="price")  # "price", "target", "stop"
    direction = Column(String(10), nullable=False)  # "above" or "below"
    price_level = Column(Float, nullable=False)
    current_price = Column(Float, nullable=True)
    message = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="active")  # active, triggered, cancelled
    triggered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="price_alerts")


class ExchangeKey(Base):
    """Encrypted exchange API credentials per user per exchange."""

    __tablename__ = "exchange_keys"
    __table_args__ = (
        UniqueConstraint("user_id", "exchange", name="uq_user_exchange"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange = Column(String(32), nullable=False)
    api_key_encrypted = Column(LargeBinary, nullable=False)
    api_secret_encrypted = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="exchange_keys")


class PortfolioBalance(Base):
    """Current free/locked/total balances per user per exchange per asset."""

    __tablename__ = "portfolio_balances"
    __table_args__ = (
        Index("ix_portfolio_balances_user_exchange", "user_id", "exchange"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange = Column(String(32), nullable=False)
    asset = Column(String(32), nullable=False)
    free = Column(Float, nullable=False)
    locked = Column(Float, nullable=False)
    total = Column(Float, nullable=False)
    usd_value = Column(Float, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="portfolio_balances")


class PortfolioPosition(Base):
    """Open futures positions per user per exchange."""

    __tablename__ = "portfolio_positions"
    __table_args__ = (
        Index("ix_portfolio_positions_user_exchange", "user_id", "exchange"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange = Column(String(32), nullable=False)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)  # "long" or "short"
    size = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    mark_price = Column(Float, nullable=False)
    pnl = Column(Float, nullable=False)
    pnl_percent = Column(Float, nullable=False)
    leverage = Column(Float, nullable=False)
    liquidation_price = Column(Float, nullable=True)
    margin = Column(Float, nullable=False)
    contract_size = Column(Float, nullable=True, default=1.0)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="portfolio_positions")


class PortfolioTrade(Base):
    """Historical trade records per user per exchange."""

    __tablename__ = "portfolio_trades"
    __table_args__ = (
        UniqueConstraint("exchange", "exchange_trade_id", "user_id", name="uq_trade_exchange_id_user"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange = Column(String(32), nullable=False)
    symbol = Column(String(20), nullable=False)
    side = Column(String(10), nullable=False)
    type = Column(String(20), nullable=False)
    price = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    cost = Column(Float, nullable=False)
    fee = Column(Float, nullable=True)
    fee_currency = Column(String(10), nullable=True)
    timestamp = Column(DateTime, nullable=False)
    exchange_trade_id = Column(String(128), nullable=False)

    user = relationship("User", back_populates="portfolio_trades")


class PortfolioSnapshot(Base):
    """Periodic portfolio value snapshots per user per exchange."""

    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        Index("ix_portfolio_snapshots_user_exchange", "user_id", "exchange"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange = Column(String(32), nullable=False)
    total_balance_usd = Column(Float, nullable=True)
    total_pnl_usd = Column(Float, nullable=False)
    open_positions = Column(Integer, nullable=False)
    timestamp = Column(DateTime, nullable=False)

    user = relationship("User", back_populates="portfolio_snapshots")


class FuturesAccountSnapshot(Base):
    """Authenticated futures account truth per user/exchange/settlement asset."""

    __tablename__ = "futures_account_snapshots"
    __table_args__ = (
        Index("ix_futures_account_snapshots_user_exchange", "user_id", "exchange", "settlement_asset", "source_ts"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange = Column(String(32), nullable=False)
    settlement_asset = Column(String(32), nullable=False)
    equity = Column(Float, nullable=True)
    available_balance = Column(Float, nullable=True)
    frozen_balance = Column(Float, nullable=True)
    cash_balance = Column(Float, nullable=True)
    position_margin = Column(Float, nullable=True)
    unrealized_pnl = Column(Float, nullable=True)
    bonus = Column(Float, nullable=True)
    available_cash = Column(Float, nullable=True)
    debt_amount = Column(Float, nullable=True)
    source_ts = Column(DateTime, nullable=False)
    synced_at = Column(DateTime, nullable=False)

    user = relationship("User", back_populates="futures_account_snapshots")


class ExchangeSyncState(Base):
    """Per-user/per-exchange/per-stream synchronization status."""

    __tablename__ = "exchange_sync_state"
    __table_args__ = (
        UniqueConstraint("user_id", "exchange", "stream", name="uq_exchange_sync_state_user_exchange_stream"),
        Index("ix_exchange_sync_state_user_exchange", "user_id", "exchange"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange = Column(String(32), nullable=False)
    stream = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)
    cursor_json = Column(JSON, nullable=True)
    oldest_source_ts = Column(DateTime, nullable=True)
    newest_source_ts = Column(DateTime, nullable=True)
    rows_fetched_total = Column(Integer, nullable=False, default=0)
    source_total = Column(Integer, nullable=True)
    complete = Column(Boolean, nullable=False, default=False)
    partial_reason = Column(String(128), nullable=True)
    unrecoverable_gaps_json = Column(JSON, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    last_attempt_at = Column(DateTime, nullable=True)
    error_code = Column(String(64), nullable=True)
    error_message_redacted = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="exchange_sync_states")


class CapitalFlowLedger(Base):
    """Idempotent capital-flow ledger (funding, transfers, deposits, withdrawals)."""

    __tablename__ = "capital_flow_ledger"
    __table_args__ = (
        Index("ix_capital_flow_user_exchange_occurred", "user_id", "exchange", "occurred_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange = Column(String(32), nullable=False)
    entry_type = Column(String(32), nullable=False)
    exchange_entry_id = Column(String(128), nullable=True)
    asset = Column(String(32), nullable=False)
    amount = Column(Float, nullable=True)
    signed_amount = Column(Float, nullable=True)
    status = Column(String(32), nullable=True)
    occurred_at = Column(DateTime, nullable=True)
    source_updated_at = Column(DateTime, nullable=True)
    synced_at = Column(DateTime, nullable=False)
    raw_json = Column(Text, nullable=True)

    user = relationship("User", back_populates="capital_flow_ledger")


class DcaShadowGlobalKillSwitch(Base):
    """Global shadow-mode ADD kill switch for all users."""

    __tablename__ = "dca_shadow_global_kill_switches"
    __table_args__ = (
        Index("ix_dca_shadow_global_kill_switches_active", "active"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    active = Column(Boolean, nullable=False, default=False)
    reason = Column(Text, nullable=True)
    created_by = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)


class DcaShadowUserKillSwitch(Base):
    """Per-user shadow-mode ADD kill switch."""

    __tablename__ = "dca_shadow_user_kill_switches"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_dca_shadow_user_kill_switch_user"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    active = Column(Boolean, nullable=False, default=False)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="dca_shadow_user_kill_switches")


class DcaShadowSymbolKillSwitch(Base):
    """Per-user, per-symbol shadow-mode ADD kill switch."""

    __tablename__ = "dca_shadow_symbol_kill_switches"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "exchange", "symbol",
            name="uq_dca_shadow_symbol_kill_switch_user_exchange_symbol",
        ),
        Index("ix_dca_shadow_symbol_kill_switch_user_exchange", "user_id", "exchange"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange = Column(String(32), nullable=False)
    symbol = Column(String(40), nullable=False)
    active = Column(Boolean, nullable=False, default=False)
    reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="dca_shadow_symbol_kill_switches")


class DcaShadowDecisionHistory(Base):
    """Audited shadow-mode DCA decision history scoped to a user."""

    __tablename__ = "dca_shadow_decision_history"
    __table_args__ = (
        Index("ix_dca_shadow_decision_history_user_exchange", "user_id", "exchange"),
        Index("ix_dca_shadow_decision_history_user_symbol", "user_id", "symbol"),
        Index("ix_dca_shadow_decision_history_user_outcome", "user_id", "final_outcome"),
        Index("ix_dca_shadow_decision_history_user_timestamp", "user_id", "timestamp"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    exchange = Column(String(32), nullable=False)
    symbol = Column(String(40), nullable=False)
    original_recommendation = Column(String(20), nullable=False)
    final_outcome = Column(String(20), nullable=False)
    gate_breakdown = Column(JSON, nullable=False)
    blocked_gates = Column(JSON, nullable=False)
    assumption_set = Column(JSON, nullable=False)
    final_reason = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="dca_shadow_decision_history")


class PositionHistory(Base):
    """Closed/historical futures positions per user per exchange.

    Persisted on each portfolio refresh so the dashboard can show a history
    of closed positions without re-fetching from the exchange.
    """

    __tablename__ = "position_history"
    exchange_position_id = Column(String(128), nullable=True)
    __table_args__ = (
        Index(
            "uq_position_history_user_exchange_source_id",
            "user_id", "exchange", "exchange_position_id",
            unique=True,
            sqlite_where=exchange_position_id.is_not(None),
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange = Column(String(32), nullable=False)
    symbol = Column(String(40), nullable=False)
    side = Column(String(10), nullable=False)  # "long" or "short"
    size = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False, default=0.0)
    pnl = Column(Float, nullable=False)
    pnl_percent = Column(Float, nullable=False, default=0.0)
    leverage = Column(Float, nullable=False, default=1.0)
    open_time = Column(DateTime, nullable=True)
    close_time = Column(DateTime, nullable=True)
    close_reason = Column(String(20), nullable=True)  # liquidated/closed/manual
    contract_size = Column(Float, nullable=True, default=1.0)
    reported_pnl = Column(Float, nullable=True)
    reported_roi_pct = Column(Float, nullable=True)
    source_state = Column(String(32), nullable=True)
    source_updated_at = Column(DateTime, nullable=True)
    synced_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="position_history")


class OrderHistory(Base):
    """Historical (closed/cancelled) orders per user per exchange.

    Persisted on each portfolio refresh so the dashboard can show order
    history without re-fetching from the exchange.
    """

    __tablename__ = "order_history"
    exchange_order_id = Column(String(128), nullable=True)
    __table_args__ = (
        Index(
            "uq_order_history_user_exchange_source_id",
            "user_id", "exchange", "exchange_order_id",
            unique=True,
            sqlite_where=exchange_order_id.is_not(None),
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange = Column(String(32), nullable=False)
    symbol = Column(String(40), nullable=False)
    type = Column(String(20), nullable=False)  # limit / market
    side = Column(String(10), nullable=False)  # buy / sell
    side_action = Column(String(20), nullable=True)  # "Open Long", "Close Short", etc.
    price = Column(Float, nullable=False)
    amount = Column(Float, nullable=False)
    filled = Column(Float, nullable=False, default=0.0)
    filled_price = Column(Float, nullable=True)
    cost = Column(Float, nullable=False, default=0.0)
    status = Column(String(20), nullable=False)  # filled / cancelled / open
    timestamp = Column(DateTime, nullable=False)
    fee = Column(Float, nullable=True, default=0.0)
    fee_currency = Column(String(20), nullable=True, default="USDT")
    leverage = Column(Float, nullable=True, default=1.0)
    reduce_only = Column(Integer, nullable=True, default=0)
    source_updated_at = Column(DateTime, nullable=True)
    synced_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="order_history")


class TradeJournalEntry(Base):
    """Manual trading journal entry — notes, tags, lessons, screenshots.

    A user can optionally link a journal entry to a closed position via
    ``position_id`` (FK → ``position_history.id``). The trade metadata
    (entry_price, exit_price, pnl) is copied at creation time for quick
    reference so the journal survives even if the linked position is later
    deleted; the fields are nullable to support manual entries that don't
    map to a recorded position.
    """

    __tablename__ = "trade_journal_entries"
    __table_args__ = (
        Index("ix_journal_user_exchange", "user_id", "exchange"),
        Index("ix_journal_user_symbol", "user_id", "symbol"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange = Column(String(32), nullable=True)  # e.g. "mexc" — nullable for manual entries
    symbol = Column(String(40), nullable=False)  # e.g. "BTCUSDT"
    position_id = Column(Integer, ForeignKey("position_history.id", ondelete="SET NULL"), nullable=True)

    notes = Column(Text, nullable=True)
    tags = Column(String(255), nullable=True)  # comma-separated: "scalp,swing,breakout"
    lessons = Column(Text, nullable=True)
    screenshots = Column(JSON, nullable=True)  # JSON array of file paths

    entry_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    pnl = Column(Float, nullable=True)

    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="journal_entries")


class RealtimeSignal(Base):
    """Latest durable advisory-signal state for a user and market direction.

    ``dedup_key`` advances only when the lifecycle changes, making restart-safe
    notification idempotency possible without retaining exchange credentials.
    """

    __tablename__ = "realtime_signals"
    __table_args__ = (
        UniqueConstraint("user_id", "pair", "direction", name="uq_realtime_signal_user_pair_direction"),
        Index("ix_realtime_signals_user_pair", "user_id", "pair"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    pair = Column(String(20), nullable=False)
    direction = Column(String(10), nullable=False)
    state = Column(String(20), nullable=False)
    dedup_key = Column(String(100), nullable=False)
    transition_count = Column(Integer, nullable=False, default=0)
    missing_gates = Column(Text, nullable=True)
    analysis_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)


class RealtimeNotification(Base):
    """Committed outbox record for at-least-once advisory delivery."""

    __tablename__ = "realtime_notifications"
    __table_args__ = (
        UniqueConstraint("signal_id", "channel_id", "dedup_key", name="uq_realtime_notification_delivery"),
        Index("ix_realtime_notifications_status", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(Integer, ForeignKey("realtime_signals.id", ondelete="CASCADE"), nullable=False)
    channel_id = Column(Integer, ForeignKey("alert_channels.id", ondelete="CASCADE"), nullable=False)
    dedup_key = Column(String(100), nullable=False)
    status = Column(String(20), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    sent_at = Column(DateTime, nullable=True)
