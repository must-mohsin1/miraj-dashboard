"""SQLAlchemy ORM models for the crypto analysis application."""

import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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
