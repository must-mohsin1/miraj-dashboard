#!/usr/bin/env python3
import os, sqlite3

db_path = os.path.join(os.path.dirname(__file__), "miraj.db")

# Remove if it exists as a directory
if os.path.isdir(db_path):
    import shutil
    shutil.rmtree(db_path)
    print(f"Removed directory: {db_path}")

conn = sqlite3.connect(db_path)
conn.execute("CREATE TABLE IF NOT EXISTS _init (id INTEGER)")
conn.close()
os.chmod(db_path, 0o644)
print(f"Created SQLite database: {db_path}")
