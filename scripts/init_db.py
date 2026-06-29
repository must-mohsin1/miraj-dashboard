#!/usr/bin/env python3
"""Initialize the database schema.

Idempotent — safe to run multiple times (uses CREATE TABLE IF NOT EXISTS).
Run this script before starting the application for the first time.
"""

import asyncio
import sys
import os
from typing import Optional

# Ensure the backend package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.database import Base, get_engine, set_db_path

# Import models so their metadata gets registered with Base
import backend.models  # noqa: F401


async def init_db(db_path: Optional[str] = None) -> None:
    """Create all tables defined in ``backend.models``.

    Args:
        db_path: Optional path to the SQLite database file.  Defaults to
                 ``DATABASE_URL`` env var, then ``crypto_analysis.db``.
    """
    if db_path:
        set_db_path(db_path)

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print(f"Database schema created successfully at: {engine.url!s}")


if __name__ == "__main__":
    db_path = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(init_db(db_path))
