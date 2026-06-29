"""SQLAlchemy ORM models for the crypto analysis application."""

import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
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
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="analyses")


class WatchlistPair(Base):
    __tablename__ = "watchlist_pairs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    pair = Column(String(20), nullable=False)  # e.g. "BTCUSDT"
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
