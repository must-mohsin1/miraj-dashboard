"""Quick verify: check head revision is valid and walk the tree."""
import sys, os
sys.path.insert(0, os.path.abspath(".."))

from alembic.config import Config
from alembic import command

cfg = Config("alembic.ini")
cfg.set_main_option("script_location", "migrations")

# Print heads
command.heads(cfg)

print("---")

# Print history
command.history(cfg)
