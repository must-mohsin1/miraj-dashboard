"""SQLAlchemy ORM models for the crypto analysis application."""

import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

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


class AlertChannel(Base):
    """Per-user Telegram / Discord alert channel configuration."""

    __tablename__ = "alert_channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    channel_type = Column(String(20), nullable=False)  # "telegram" or "discord"
    config = Column(Text, nullable=True)                # JSON: {"chat_id": "123"} or {"webhook_url": "https://..."}
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
    channel = Column(String(20), nullable=False)   # "telegram" or "discord"
    score = Column(Float, nullable=True)
    direction = Column(String(10), nullable=True)  # LONG / SHORT
    message = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default="sent")  # sent, failed
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="alert_histories")


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

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange = Column(String(32), nullable=False)
    total_balance_usd = Column(Float, nullable=True)
    total_pnl_usd = Column(Float, nullable=False)
    open_positions = Column(Integer, nullable=False)
    timestamp = Column(DateTime, nullable=False)

    user = relationship("User", back_populates="portfolio_snapshots")
