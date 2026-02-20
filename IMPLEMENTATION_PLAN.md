# Ops Agent - Implementation Plan

**Version:** MVP-1  
**Date:** 2024  
**Status:** Ready for Implementation

---

## Overview

A FastAPI-based service that accepts application-level error logs in JSON format, analyzes them using AI, and generates Root Cause Analysis (RCA) reports.

## Requirements

- **Log Type:** Application-level, JSON structured
- **Database:** PostgreSQL
- **Authentication:** None (to be added later)
- **Processing:** Synchronous (immediate response)
- **Storage:** Metadata + Analysis Results only (lightweight)
- **AI Integration:** Interface only, ready for Opencode integration

---

## Project Structure

```
ops-agent/
├── alembic/
│   ├── versions/
│   └── env.py
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app entry
│   ├── config.py               # Settings & configuration
│   ├── database.py             # Database connection
│   ├── dependencies.py         # FastAPI dependencies
│   ├── core/
│   │   ├── __init__.py
│   │   ├── exceptions.py       # Custom exceptions
│   │   └── logger.py           # Logging configuration
│   ├── models/
│   │   ├── __init__.py
│   │   ├── log_entry.py        # LogEntry SQLAlchemy model
│   │   └── analysis.py         # AnalysisResult SQLAlchemy model
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── log.py              # Log input/output schemas
│   │   └── analysis.py         # Analysis schemas
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── logs.py             # Log upload endpoints
│   │   └── analysis.py         # Analysis query endpoints
│   └── services/
│       ├── __init__.py
│       ├── log_parser.py       # Log parsing service
│       ├── ai_analyzer.py      # AI analyzer interface
│       └── rca_generator.py    # RCA generation service
├── alembic.ini
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

---

## Database Schema

### Table: log_entries

Stores log metadata (not full logs - lightweight storage).

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | PK | Unique identifier |
| log_hash | VARCHAR(64) | UNIQUE | SHA256 hash of original log |
| source | VARCHAR(100) | NOT NULL | Service/app name |
| level | VARCHAR(20) | NOT NULL | ERROR/WARN/INFO/DEBUG |
| timestamp | TIMESTAMP | NOT NULL | Original log timestamp |
| message_preview | VARCHAR(500) | | First 500 chars of message |
| has_analysis | BOOLEAN | DEFAULT FALSE | Analysis exists flag |
| created_at | TIMESTAMP | DEFAULT NOW() | Record creation time |

### Table: analysis_results

Stores AI-generated RCA results.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | UUID | PK | Unique identifier |
| log_entry_id | UUID | FK → log_entries.id | Reference to log |
| summary | TEXT | NOT NULL | Error summary |
| root_cause | TEXT | NOT NULL | Root cause analysis |
| components | JSONB | | Affected components list |
| confidence | FLOAT | | AI confidence score (0.0-1.0) |
| analyzed_at | TIMESTAMP | DEFAULT NOW() | Analysis timestamp |
| processing_time_ms | INTEGER | | Analysis duration in ms |

---

## API Endpoints

### POST /api/v1/logs/analyze
Upload log and get immediate analysis.

**Request Body:**
```json
{
  "timestamp": "2024-01-15T10:23:45Z",
  "level": "ERROR",
  "service": "auth-service",
  "message": "Connection timeout to database",
  "trace_id": "abc-123-xyz",
  "metadata": {"user_id": "12345"}
}
```

**Response:**
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "log_id": "550e8400-e29b-41d4-a716-446655440001",
  "summary": "Database connection timeout in auth-service",
  "root_cause": "The auth-service failed to connect to PostgreSQL database due to connection pool exhaustion",
  "affected_components": [
    {"name": "auth-service", "type": "service", "impact_level": "critical"},
    {"name": "postgres-db", "type": "database", "impact_level": "high"}
  ],
  "confidence": 0.92,
  "analyzed_at": "2024-01-15T10:23:50Z",
  "processing_time_ms": 450
}
```

### GET /api/v1/analysis/{analysis_id}
Get specific analysis by ID.

### GET /api/v1/analysis
List all analyses with pagination.

**Query Parameters:**
- `skip`: Offset (default: 0)
- `limit`: Page size (default: 20, max: 100)
- `service`: Filter by service name
- `start_date`: Filter from date
- `end_date`: Filter to date

### GET /api/v1/logs/{log_id}/analysis
Get analysis for specific log entry.

### GET /health
Health check endpoint.

---

## Implementation Phases

### Phase 1: Database & Models (Priority: HIGH)

**Files to Create:**

1. **app/config.py**
   - Pydantic Settings with PostgreSQL connection
   - Environment variable loading
   - Database URL configuration

2. **app/database.py**
   - SQLAlchemy async engine setup
   - Session management
   - Base model definition

3. **app/models/log_entry.py**
   - LogEntry SQLAlchemy model
   - Fields: id, log_hash, source, level, timestamp, message_preview, has_analysis, created_at

4. **app/models/analysis.py**
   - AnalysisResult SQLAlchemy model
   - Fields: id, log_entry_id, summary, root_cause, components, confidence, analyzed_at, processing_time_ms
   - Relationship to LogEntry

5. **app/schemas/log.py**
   - LogEntryInput Pydantic model
   - LogEntryResponse Pydantic model
   - Validation for log level enum

6. **app/schemas/analysis.py**
   - ComponentImpact Pydantic model
   - AnalysisResult Pydantic model
   - AnalysisListResponse Pydantic model
   - Severity enum

7. **alembic/**
   - Initialize Alembic
   - Create initial migration
   - Migration scripts for log_entries and analysis_results tables

### Phase 2: Core Services (Priority: HIGH)

**Files to Create:**

8. **app/services/log_parser.py**
   - LogParser class
   - parse() method: Extract and validate log fields
   - generate_hash() method: Create SHA256 hash for deduplication
   - normalize_timestamp() method: Standardize timestamp formats

9. **app/services/ai_analyzer.py**
   - AIAnalyzerInterface (ABC)
     - analyze(log: ParsedLog) -> RawAnalysis
     - get_capabilities() -> Dict
   - MockAnalyzer implementation
     - Returns structured mock data for development
     - Simulates processing delay
   - RawAnalysis dataclass

10. **app/services/rca_generator.py**
    - RCAGenerator class
    - generate(raw_analysis, log) -> AnalysisResult
    - structure_components(raw_text) -> List[ComponentImpact]

11. **app/core/exceptions.py**
    - LogParseError
    - AnalysisError
    - LogNotFoundError
    - DuplicateLogError

### Phase 3: API Layer (Priority: HIGH)

**Files to Create:**

12. **app/routers/logs.py**
    - POST /api/v1/logs/analyze endpoint
    - Input validation
    - Call LogParser
    - Check for duplicate (by hash)
    - Call AIAnalyzer
    - Call RCAGenerator
    - Save to database
    - Return AnalysisResult

13. **app/routers/analysis.py**
    - GET /api/v1/analysis/{analysis_id}
    - GET /api/v1/analysis (with filters)
    - GET /api/v1/logs/{log_id}/analysis
    - Pagination logic
    - Filter implementation

14. **app/dependencies.py**
    - get_db() - Database session dependency
    - get_log_parser() - LogParser instance
    - get_ai_analyzer() - AIAnalyzer instance
    - get_rca_generator() - RCAGenerator instance

15. **app/main.py**
    - FastAPI app initialization
    - CORS middleware
    - Include routers
    - Health check endpoint
    - Exception handlers

### Phase 4: Infrastructure (Priority: MEDIUM)

**Files to Create:**

16. **docker-compose.yml**
    - PostgreSQL 15 service
    - Volume for data persistence
    - Environment variables

17. **requirements.txt**
    ```
    fastapi==0.115.0
    uvicorn[standard]==0.32.0
    pydantic==2.10.0
    pydantic-settings==2.7.0
    sqlalchemy[asyncio]==2.0.36
    asyncpg==0.30.0
    alembic==1.14.0
    python-json-logger==2.0.7
    httpx==0.28.0
    pytest==8.3.4
    pytest-asyncio==0.25.0
    ```

18. **.env.example**
    ```
    DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/loganalyser
    DEBUG=True
    APP_NAME=Ops Agent
    ```

19. **README.md**
    - Project description
    - Setup instructions
    - API documentation
    - Database setup
    - Running locally

20. **alembic.ini**
    - Alembic configuration
    - Database URL from environment

---

## Data Models Reference

### LogEntryInput Schema
```python
class LogEntryInput(BaseModel):
    timestamp: datetime
    level: str = Field(..., pattern="^(ERROR|WARN|INFO|DEBUG)$")
    service: str = Field(..., min_length=1, max_length=100)
    message: str = Field(..., min_length=1)
    trace_id: Optional[str] = Field(None, max_length=100)
    metadata: Optional[Dict[str, Any]] = None
```

### AnalysisResult Schema
```python
class AnalysisResult(BaseModel):
    id: UUID
    log_id: UUID
    summary: str
    root_cause: str
    affected_components: List[ComponentImpact]
    confidence: float = Field(..., ge=0.0, le=1.0)
    analyzed_at: datetime
    processing_time_ms: int
```

### ComponentImpact Schema
```python
class ComponentImpact(BaseModel):
    name: str
    type: str  # service, database, cache, api, queue, external
    impact_level: str  # critical, high, medium, low
```

---

## Dependencies

### Core Dependencies
- `fastapi` - Web framework
- `uvicorn` - ASGI server
- `pydantic` - Data validation
- `pydantic-settings` - Configuration management

### Database Dependencies
- `sqlalchemy[asyncio]` - ORM with async support
- `asyncpg` - Async PostgreSQL driver
- `alembic` - Database migrations

### Utility Dependencies
- `python-json-logger` - JSON logging
- `httpx` - HTTP client (for future AI integration)

### Development Dependencies
- `pytest` - Testing framework
- `pytest-asyncio` - Async test support

---

## Database Migrations

### Migration 1: Create log_entries table
```sql
CREATE TABLE log_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    log_hash VARCHAR(64) UNIQUE NOT NULL,
    source VARCHAR(100) NOT NULL,
    level VARCHAR(20) NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    message_preview VARCHAR(500),
    has_analysis BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_log_entries_source ON log_entries(source);
CREATE INDEX idx_log_entries_level ON log_entries(level);
CREATE INDEX idx_log_entries_timestamp ON log_entries(timestamp);
CREATE INDEX idx_log_entries_created_at ON log_entries(created_at);
```

### Migration 2: Create analysis_results table
```sql
CREATE TABLE analysis_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    log_entry_id UUID NOT NULL REFERENCES log_entries(id) ON DELETE CASCADE,
    summary TEXT NOT NULL,
    root_cause TEXT NOT NULL,
    components JSONB,
    confidence FLOAT,
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processing_time_ms INTEGER,
    UNIQUE(log_entry_id)
);

CREATE INDEX idx_analysis_results_analyzed_at ON analysis_results(analyzed_at);
```

---

## Service Interfaces

### LogParser
```python
class LogParser:
    def parse(self, log_data: Dict[str, Any]) -> ParsedLog
    def generate_hash(self, log_data: Dict[str, Any]) -> str
    def normalize_timestamp(self, timestamp: Union[str, datetime]) -> datetime
```

### AIAnalyzerInterface
```python
class AIAnalyzerInterface(ABC):
    @abstractmethod
    async def analyze(self, log: ParsedLog) -> RawAnalysis
    
    @abstractmethod
    def get_capabilities(self) -> Dict[str, Any]
```

### RCAGenerator
```python
class RCAGenerator:
    def generate(self, raw_analysis: RawAnalysis, log: ParsedLog) -> AnalysisResult
    def structure_components(self, raw_text: str) -> List[ComponentImpact]
```

---

## Error Handling Strategy

### Custom Exceptions
- `LogParseError` - Invalid log format
- `DuplicateLogError` - Log already exists (by hash)
- `AnalysisError` - AI analysis failure
- `LogNotFoundError` - Log ID not found
- `AnalysisNotFoundError` - Analysis ID not found

### HTTP Status Codes
- `200 OK` - Successful GET requests
- `201 Created` - Successful POST requests
- `400 Bad Request` - Invalid input data
- `404 Not Found` - Resource not found
- `409 Conflict` - Duplicate log entry
- `500 Internal Server Error` - Processing errors

---

## Testing Strategy

### Unit Tests
- Test LogParser with various log formats
- Test MockAnalyzer returns valid structure
- Test RCAGenerator structures data correctly

### Integration Tests
- Test API endpoints with test client
- Test database operations
- Test full analysis flow end-to-end

### Test Data
- Sample JSON logs for different error types
- Edge cases (empty messages, special characters)
- Large log entries (>500 chars)

---

## Future Enhancements (Post MVP-1)

### MVP-2 Features
- Severity determination (SeverityEnum, severity column, _determine_severity heuristics)
- Suggested fixes in analysis (SuggestedFix schema, FixCategory enum, suggestions JSONB column)
- Authentication (API keys, JWT)
- Asynchronous processing with Celery
- Webhook notifications
- Batch log upload
- Log patterns/statistics dashboard

### MVP-3 Features
- Real log storage (S3/MinIO) with metadata reference
- Advanced filtering and search
- Export analysis reports (PDF, HTML)
- Integration with monitoring tools (PagerDuty, Slack)

### AI Integration
- Opencode integration
- Support for multiple AI providers (OpenAI, Anthropic)
- Custom model fine-tuning
- Confidence threshold configuration

---

## Setup Instructions

### Local Development

1. **Start PostgreSQL**
   ```bash
   docker-compose up -d postgres
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Setup environment**
   ```bash
   cp .env.example .env
   # Edit .env with your settings
   ```

5. **Run migrations**
   ```bash
   alembic upgrade head
   ```

6. **Start server**
   ```bash
   uvicorn app.main:app --reload
   ```

7. **Test API**
   ```bash
   curl -X POST http://localhost:8000/api/v1/logs/analyze \
     -H "Content-Type: application/json" \
     -d '{
       "timestamp": "2024-01-15T10:23:45Z",
       "level": "ERROR",
       "service": "auth-service",
       "message": "Connection timeout to database"
     }'
   ```

---

## Success Criteria

### Functional Requirements
- ✅ Accept JSON structured logs via API
- ✅ Generate SHA256 hash for deduplication
- ✅ Store log metadata in PostgreSQL
- ✅ Generate RCA with summary, root cause, components
- ✅ Provide confidence scores
- ✅ Query analysis history with filters
- ✅ Return processing time metrics

### Non-Functional Requirements
- ✅ Response time < 2 seconds for analysis
- ✅ Support concurrent requests
- ✅ Handle logs up to 10KB in metadata
- ✅ Store 90 days of analysis history
- ✅ 99% uptime for API endpoints

---

## Notes

- Keep AI analyzer as interface only for MVP-1
- Mock analyzer should return realistic dummy data
- Log deduplication prevents re-analyzing identical logs
- Processing time tracking helps optimize later
- All timestamps should be UTC
- JSONB fields for flexible component storage

---

**Status:** ✅ Ready for Implementation  
**Next Step:** Begin Phase 1 - Database & Models
