# Miraj Dashboard — Crypto Analysis Platform

A crypto trading analysis platform with a FastAPI backend and Streamlit dashboard.
Runs the full analysis pipeline: macro data → OHLCV → indicators → QQE Mod → SMC
→ patterns → confluence scoring → trade plan → charts.

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
│   ├── routes/
│   │   ├── auth.py             # /api/v1/auth (register, login)
│   │   ├── macro.py            # /api/v1/macro
│   │   └── scan.py             # /api/v1/scan/{symbol}
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

| Method | Path                  | Auth     | Description               |
|--------|-----------------------|----------|---------------------------|
| POST   | /api/v1/auth/register | No       | Create account            |
| POST   | /api/v1/auth/login    | No       | Sign in, get JWT token    |
| GET    | /api/v1/macro         | JWT      | Macro market data         |
| POST   | /api/v1/scan/{symbol} | JWT      | Run full analysis         |
| GET    | /api/v1/scan/{symbol} | JWT      | Get cached analysis       |
| GET    | /api/v1/protected     | JWT      | Verify auth status        |
| GET    | /health               | No       | Health check              |

## Environment Variables

| Variable              | Required | Default | Description                    |
|-----------------------|----------|---------|--------------------------------|
| `DATABASE_URL`        | No       | `sqlite+aiosqlite:///./miraj.db` | Database connection string |
| `JWT_SECRET_KEY`      | **Yes**  | —       | JWT signing secret (generate!) |
| `JWT_EXPIRE_MINUTES`  | No       | 60      | Token expiry in minutes        |
| `TELEGRAM_BOT_TOKEN`  | No       | —       | Telegram bot token (optional)  |
| `OBSIDIAN_VAULT_PATH` | No       | —       | Obsidian vault path (optional) |
| `FRED_API_KEY`        | No       | —       | FRED API key (macro data)      |

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
