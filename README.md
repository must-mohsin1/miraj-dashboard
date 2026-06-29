# Miraj Dashboard — Crypto Analysis Platform

A crypto trading analysis platform with a FastAPI backend and Streamlit dashboard.
Runs the full analysis pipeline: macro data → OHLCV → indicators → QQE Mod → SMC
→ patterns → confluence scoring → trade plan → charts.

## Features

### Phase 1 — Core Analysis
- Macro data dashboard (real-time economic indicators)
- Single-pair confluence analysis (technicals + patterns + SMC)
- Trade plan generation (entry, stop-loss, take-profit levels)
- Interactive chart visualization with mplfinance

### Phase 2 — Watchlist & Automation
- **Watchlist management** — Add, reorder, and delete watched crypto pairs with persistent storage
- **Batch scanning** — Run full analysis on all watchlist pairs simultaneously with rate limiting
- **Scheduled scans** — APScheduler runs analysis every 4 hours automatically on startup, tracking each cycle in `scan_runs`
- **Analysis history** — Paginated, filterable history (by symbol, date, min_score) with delete and markdown export
- **Settings page** — Manage watchlist pairs, configure alert thresholds, and view account details

### Phase 3 — Alerts & Sync
- **Telegram alerts** — Receive real-time trade alerts via Telegram bot when confluence scores exceed per-pair thresholds, with MarkdownV2-formatted messages
- **Discord alerts** — Rich embedded alert delivery via Discord webhooks with customisable webhook URL validation
- **Alert manager** — Configurable per-pair thresholds (`alert_threshold`), per-pair mute toggle (`alert_enabled`), cooldown dedup (4h default per symbol), and multi-channel routing
- **Alert channels** — Manage Telegram (chat_id) and Discord (webhook_url) channels via Settings API; each channel can be individually enabled/disabled
- **Alert history** — Every send attempt (success or failure) is logged in `alert_histories` for audit and dedup
- **Daily digest** — Scheduled Telegram summary (configurable time, default 20:00 UTC) of all pairs scanned that day, sorted by confluence score with high-confluence and actionable counts
- **Obsidian vault sync** — Automatic export of analysis reports as markdown files and mplfinance chart PNGs to an Obsidian vault, toggleable per pair
- **Settings API** — CRUD endpoints for alert channels and per-pair settings (`alert_threshold`, `alert_enabled`)

## Quick Start

### 1. Clone and configure

```bash
cp .env.example .env
# Edit .env — set JWT_SECRET_KEY to a secure random value:
#   python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

### 2. Run with Docker Compose

```bash
docker compose up --build
```

- **Backend API** → http://localhost:8000
- **Dashboard** → http://localhost:8501
- **Health check** → http://localhost:8000/health

### 3. Login

1. Open the dashboard at http://localhost:8501
2. Create an account (email + password)
3. Sign in and explore the Macro Dashboard, Scanner, and Analysis pages

## Project Structure

```
.
├── docker-compose.yml          # web (FastAPI :8000) + dashboard (Streamlit :8501)
├── Dockerfile.web              # Python 3.11-slim, uvicorn
├── Dockerfile.streamlit        # Python 3.11-slim, streamlit
├── .env.example                # Environment variable template
├── setup.py                    # mirai_core package installer
│
├── backend/                    # FastAPI application
│   ├── main.py                 # Entry point, router registration
│   ├── auth.py                 # JWT + bcrypt authentication
│   ├── database.py             # SQLAlchemy async engine + sessions
│   ├── models.py               # SQLAlchemy ORM models
│   ├── schemas.py              # Pydantic request/response schemas
│   ├── alerts/                 # Phase 3 — alert delivery system
│   │   ├── __init__.py         # AlertManager public API
│   │   ├── manager.py          # Threshold filtering, dedup, channel routing
│   │   ├── telegram.py         # Telegram Bot API client + message formatter
│   │   ├── discord.py          # Discord webhook sender + embed builder
│   │   └── digest.py           # Daily digest builder + Telegram client
│   ├── obsidian.py             # Phase 3 — Obsidian vault sync service
│   ├── scheduler.py            # APScheduler: 4-hour scans + daily digest
│   ├── routes/
│   │   ├── auth.py             # /api/v1/auth (register, login)
│   │   ├── macro.py            # /api/v1/macro
│   │   ├── scan.py             # /api/v1/scan/{symbol} — single + batch
│   │   ├── watchlist.py        # /api/v1/watchlist CRUD + batch scan
│   │   ├── history.py          # /api/v1/history (paginated, export)
│   │   └── settings.py         # /api/v1/settings (pair settings + alert channels)
│   └── services/
│       ├── macro_service.py    # Macro data fetching + caching
│       └── analysis_service.py # Full pipeline orchestration
│
├── dashboard/                  # Streamlit dashboard
│   ├── app.py                  # Entry point, auth gate, navigation
│   ├── utils/
│   │   ├── api_client.py       # HTTP client helpers
│   │   └── session.py          # JWT session state management
│   ├── components/
│   │   ├── macro_cards.py      # Macro dashboard card components
│   │   ├── chart_viewer.py     # Interactive Plotly chart
│   │   └── score_chart.py      # Score breakdown bar chart
│   └── pages/
│       ├── home.py             # Home / landing page
│       ├── macro.py            # Macro Dashboard
│       ├── scanner.py          # Pair scanner
│       ├── analysis.py         # Analysis detail page
│       ├── history.py          # Analysis history
│       └── settings.py         # User settings
│
├── mirai_core/                 # Core analysis engine (pip-installable)
│   ├── config.py               # Configuration constants
│   ├── ohlcv.py                # OHLCV data fetching (yfinance)
│   ├── macro.py                # Macro data sources
│   ├── indicators.py           # Technical indicators (RSI, EMA, BB)
│   ├── qqe_mod.py              # QQE Mod indicator
│   ├── smc.py                  # Smart Money Concepts
│   ├── patterns.py             # Chart pattern detection
│   ├── confluence.py           # Confluence scoring engine
│   ├── trade_plan.py           # Trade plan generator
│   └── charts.py               # Plotly chart helpers
│
├── scripts/
│   ├── init_db.py              # Database initialisation
│   └── seed_pairs.py           # Seed default watchlist pairs
│
├── requirements-web.txt        # Backend Python dependencies
├── requirements-dash.txt       # Dashboard-specific dependencies
└── requirements.txt            # Combined dependencies (dev)
```

## API Endpoints

| Method | Path                              | Auth     | Description                          |
|--------|-----------------------------------|----------|--------------------------------------|
| POST   | /api/v1/auth/register             | No       | Create account                       |
| POST   | /api/v1/auth/login                | No       | Sign in, get JWT token               |
| GET    | /api/v1/macro                     | JWT      | Macro market data                    |
| POST   | /api/v1/scan/{symbol}             | JWT      | Run full analysis                    |
| GET    | /api/v1/scan/{symbol}             | JWT      | Get cached analysis                  |
| POST   | /api/v1/scan/batch                | JWT      | Batch scan watchlist pairs           |
| GET    | /api/v1/watchlist                 | JWT      | List watchlist pairs                 |
| POST   | /api/v1/watchlist                 | JWT      | Add pair to watchlist                |
| DELETE | /api/v1/watchlist/{pair_id}       | JWT      | Remove pair from watchlist           |
| PUT    | /api/v1/watchlist/reorder         | JWT      | Reorder watchlist pairs              |
| GET    | /api/v1/history                   | JWT      | Paginated analysis history           |
| DELETE | /api/v1/history/{id}              | JWT      | Delete analysis record               |
| GET    | /api/v1/history/export            | JWT      | Export history as markdown           |
| GET    | /api/v1/settings/pairs            | JWT      | List per-pair alert settings         |
| PUT    | /api/v1/settings/pairs/{pair}     | JWT      | Update pair alert settings (upsert)  |
| GET    | /api/v1/settings/channels         | JWT      | List alert channels                  |
| POST   | /api/v1/settings/channels         | JWT      | Create alert channel (Telegram/Discord)|
| PUT    | /api/v1/settings/channels/{id}    | JWT      | Update alert channel config          |
| DELETE | /api/v1/settings/channels/{id}    | JWT      | Delete alert channel                 |
| GET    | /api/v1/protected                 | JWT      | Verify auth status                   |
| GET    | /health                           | No       | Health check                         |

## Environment Variables

| Variable              | Required | Default | Description                               |
|-----------------------|----------|---------|-------------------------------------------|
| `DATABASE_URL`        | No       | `sqlite+aiosqlite:///./miraj.db` | Database connection string |
| `JWT_SECRET_KEY`      | **Yes**  | —       | JWT signing secret (generate!)            |
| `JWT_EXPIRE_MINUTES`  | No       | 60      | Token expiry in minutes                   |
| `TELEGRAM_BOT_TOKEN`  | No       | —       | Telegram bot token (alerts + digest)      |
| `DISCORD_WEBHOOK_URL` | No       | —       | Default Discord webhook URL               |
| `OBSIDIAN_VAULT_PATH` | No       | —       | Path to Obsidian vault for sync           |
| `DIGEST_HOUR`         | No       | 20      | Daily digest hour (UTC, 0-23)             |
| `DIGEST_MINUTE`       | No       | 0       | Daily digest minute (UTC, 0-59)           |
| `FRED_API_KEY`        | No       | —       | FRED API key for macro data               |
| `MIRAI_CORE_PATH`     | No       | —       | Path to mirai_core package                |

## Development

### Without Docker

```bash
# Create and activate virtualenv
python -m venv .venv && source .venv/bin/activate

# Install dependencies
pip install -r requirements-web.txt
pip install -e .  # install mirai_core in editable mode

# Set JWT secret (required)
export JWT_SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')

# Start backend
uvicorn backend.main:app --reload --port 8000

# In another terminal, start dashboard
pip install -r requirements-dash.txt
streamlit run dashboard/app.py
```
