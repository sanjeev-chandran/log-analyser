# Log Analysis & RCA Generator

A FastAPI-based service for analyzing application logs and generating Root Cause Analysis (RCA) reports.

## Quick Start with Docker

### Prerequisites
- Docker Engine 20.10+
- Docker Compose 2.0+

### Running with Docker Compose

1. **Clone and navigate to the project:**
   ```bash
   cd log-analyser
   ```

2. **Configure your LLM provider** (set at least one API key in `.env`):
   ```bash
   cp .env.example .env
   # Edit .env and set your provider key, e.g.:
   #   ANTHROPIC_API_KEY=sk-ant-...
   #   or OPENAI_API_KEY=sk-...
   ```

3. **Start the services** (postgres + opencode + api):
   ```bash
   docker compose up -d
   ```

4. **Run database migrations:**
   ```bash
   docker compose exec api alembic upgrade head
   ```

5. **Access the API:**
   - API Documentation: http://localhost:8000/docs
   - Health Check: http://localhost:8000/health
   - OpenCode server: http://localhost:4096

### Stopping the services

```bash
docker-compose down
```

To remove volumes (deletes database data):
```bash
docker-compose down -v
```

## Development Setup

### Without Docker

1. **Start PostgreSQL:**
   ```bash
   docker-compose up -d postgres
   ```

2. **Create virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Setup environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

5. **Run migrations:**
   ```bash
   alembic upgrade head
   ```

6. **Start the server:**
   ```bash
   uvicorn app.main:app --reload
   ```

## API Usage

### Analyze a Log

```bash
curl -X POST http://localhost:8000/api/v1/logs/analyze \
  -H "Content-Type: application/json" \
  -d '{
    "timestamp": "2024-01-15T10:23:45Z",
    "level": "ERROR",
    "service": "auth-service",
    "message": "Connection timeout to database",
    "trace_id": "abc-123-xyz"
  }'
```

### Get Analysis History

```bash
curl http://localhost:8000/api/v1/analysis
```

## Environment Variables

### Application

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection URL | `postgresql+asyncpg://loguser:logpassword@postgres:5432/loganalyser` |
| `DEBUG` | Enable debug mode | `False` |
| `APP_NAME` | Application name | `Log Analysis & RCA Generator` |
| `POSTGRES_USER` | PostgreSQL username | `loguser` |
| `POSTGRES_PASSWORD` | PostgreSQL password | `logpassword` |
| `POSTGRES_DB` | PostgreSQL database name | `loganalyser` |

### OpenCode AI Agent

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENCODE_SERVER_URL` | URL of the OpenCode server (empty = mock analyzer) | _(empty)_ |
| `OPENCODE_PROVIDER_ID` | Provider id configured in OpenCode (e.g. `anthropic`) | _(server default)_ |
| `OPENCODE_MODEL_ID` | Model id to use (e.g. `claude-sonnet-4-20250514`) | _(server default)_ |
| `OPENCODE_SERVER_PASSWORD` | Optional basic-auth password for the server | _(empty)_ |
| `OPENCODE_SERVER_USERNAME` | Optional basic-auth username | `opencode` |
| `OPENCODE_TIMEOUT` | HTTP timeout in seconds for OpenCode requests | `60.0` |

### LLM Provider Keys (passed to the OpenCode container)

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key |
| `OPENAI_API_KEY` | OpenAI API key |
| `OPENROUTER_API_KEY` | OpenRouter API key |

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                      Docker Network                              │
│                                                                  │
│  ┌──────────────┐   ┌─────────────────┐   ┌──────────────────┐ │
│  │   postgres    │   │       api       │   │    opencode      │ │
│  │   :5432       │◄──│     :8000       │──►│     :4096        │ │
│  │               │   │    (FastAPI)    │   │  (opencode serve)│ │
│  │  Log storage  │   │                 │   │                  │ │
│  │  & analysis   │   │  Log parsing    │   │  LLM proxy —     │ │
│  │  results      │   │  RCA pipeline   │   │  forwards to     │ │
│  │               │   │  REST API       │   │  Anthropic /     │ │
│  └──────────────┘   └─────────────────┘   │  OpenAI /        │ │
│                                            │  Ollama / etc.   │ │
│                                            └────────┬─────────┘ │
└─────────────────────────────────────────────────────┼───────────┘
                                                      │
                                                      ▼
                                              LLM Provider API
                                          (cloud or self-hosted)
```

### Services

| Service | Image | Port | Role |
|---------|-------|------|------|
| **postgres** | `postgres:15-alpine` | 5432 (host: 5433) | Stores log entries, analysis results, and migration state |
| **api** | `python:3.14-slim` (custom) | 8000 | FastAPI app — accepts logs, runs the RCA pipeline, serves REST API |
| **opencode** | `node:22-slim` (custom) | 4096 | Headless OpenCode server — proxies LLM requests to the configured provider |

### Request flow

1. Client sends a log entry to `POST /api/v1/logs/analyze`
2. **api** parses and validates the log, deduplicates via SHA-256 hash
3. **api** calls `OpenCodeAnalyzer` which creates a session on the **opencode** server
4. **opencode** forwards the prompt to the configured LLM provider and returns structured JSON
5. **api** parses the AI response into an RCA report, persists it to **postgres**, and returns it to the client

### Analyzer selection

The analyzer is selected at startup based on the `OPENCODE_SERVER_URL` environment variable:

| `OPENCODE_SERVER_URL` | Analyzer used | Use case |
|---|---|---|
| Set (e.g. `http://opencode:4096`) | `OpenCodeAnalyzer` | Production / Docker Compose — real LLM analysis |
| Empty / unset | `MockAnalyzer` | Development / testing — deterministic mock responses |

### Tech stack

- **FastAPI** — Web framework for API endpoints
- **PostgreSQL** — Database for storing log metadata and analysis results
- **SQLAlchemy** — ORM for database operations
- **Alembic** — Database migrations
- **Pydantic** — Data validation and serialization
- **OpenCode** — Headless AI agent server (LLM provider proxy)
- **httpx** — Async HTTP client for api-to-opencode communication

## Features

- JSON structured log analysis
- SHA256 hash-based deduplication
- AI-powered Root Cause Analysis (RCA) via OpenCode agent
- Severity classification (CRITICAL/HIGH/MEDIUM/LOW)
- Confidence scoring
- Affected component detection
- Analysis history with pagination
- RESTful API with auto-generated documentation
- Dockerised 3-service stack (postgres + api + opencode)

## Production Deployment

### Using Docker

1. **Set production environment variables:**
   ```bash
   export DEBUG=False
   export DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
   export ANTHROPIC_API_KEY=sk-ant-...          # or OPENAI_API_KEY / OPENROUTER_API_KEY
   export OPENCODE_PROVIDER_ID=anthropic         # optional: pin provider
   export OPENCODE_MODEL_ID=claude-sonnet-4-20250514  # optional: pin model
   ```

2. **Build and run:**
   ```bash
   docker compose up -d --build
   ```

### Health Checks

The application includes a health check endpoint:
```bash
curl http://localhost:8000/health
```

## License

MIT
