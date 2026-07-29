"""Focused source tests for the approved Option A SQLite WAL compose topology.

These tests intentionally inspect only repository-local example/config files. They do
not read .env, open any SQLite database, contact exchanges, or start production
services.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
GITIGNORE = REPO_ROOT / ".gitignore"
REQUIRED_SQLITE_DATA_MOUNT = "${SQLITE_DATA_DIR:?set SQLITE_DATA_DIR}:/app/db"
CONTAINER_DATABASE_URL = "DATABASE_URL=/app/db/crypto_analysis.db"
LEGACY_SINGLE_FILE_MOUNT = "./crypto_analysis.db:/app/crypto_analysis.db"
OPTIONAL_LOCAL_ENV_FILE = "env_file:\n      - path: .env\n        required: false"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _service_block(compose_text: str, service_name: str) -> str:
    marker = f"  {service_name}:\n"
    start = compose_text.index(marker)
    next_service = compose_text.find("\n  ", start + len(marker))
    while next_service != -1 and compose_text[next_service + 3 : next_service + 4] == " ":
        next_service = compose_text.find("\n  ", next_service + 1)
    if next_service == -1:
        return compose_text[start:]
    return compose_text[start:next_service]


def _line_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in _read(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_backend_services_share_required_sqlite_data_dir_mount_and_db_url():
    compose_text = _read(COMPOSE_FILE)

    for service_name in ("web", "monitor"):
        block = _service_block(compose_text, service_name)
        assert REQUIRED_SQLITE_DATA_MOUNT in block, (
            f"{service_name} must mount the required SQLITE_DATA_DIR host "
            "directory to /app/db so crypto_analysis.db, -wal, and -shm are "
            "co-located on one shared filesystem"
        )
        assert CONTAINER_DATABASE_URL in block, (
            f"{service_name} must receive compose-owned "
            f"{CONTAINER_DATABASE_URL}"
        )
        assert LEGACY_SINGLE_FILE_MOUNT not in block, (
            f"{service_name} must not keep the legacy single-file SQLite bind"
        )


def test_no_service_uses_legacy_single_db_file_bind_and_nextjs_has_no_db_mount():
    compose_text = _read(COMPOSE_FILE)

    assert LEGACY_SINGLE_FILE_MOUNT not in compose_text

    nextjs_block = _service_block(compose_text, "nextjs")
    assert "crypto_analysis.db" not in nextjs_block
    assert "/app/db" not in nextjs_block
    assert "SQLITE_DATA_DIR" not in nextjs_block


def test_private_env_file_is_optional_for_local_compose_validation():
    compose_text = _read(COMPOSE_FILE)

    for service_name in ("web", "monitor", "dashboard"):
        block = _service_block(compose_text, service_name)
        assert OPTIONAL_LOCAL_ENV_FILE in block, (
            f"{service_name} must not require a private repo-root .env for "
            "docker compose config with explicit SQLITE_DATA_DIR"
        )


def test_env_example_preserves_local_db_default_and_adds_sqlite_data_dir():
    values = _line_values(ENV_EXAMPLE)

    assert values.get("DATABASE_URL") == "sqlite+aiosqlite:///./miraj.db"
    assert values.get("SQLITE_DATA_DIR") == "./.runtime/sqlite"
    assert values.get("DATABASE_URL") != "/app/db/crypto_analysis.db"


def test_gitignore_ignores_runtime_sqlite_directory_and_wal_sidecars():
    patterns = {
        line.strip()
        for line in _read(GITIGNORE).splitlines()
        if line.strip() and not line.strip().startswith("#")
    }

    assert ".runtime/" in patterns
    assert "*.db-wal" in patterns
    assert "*.db-shm" in patterns
