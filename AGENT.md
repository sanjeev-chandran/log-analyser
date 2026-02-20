# AGENT.md - Agent Rules and Guidelines

## Project: Log Analysis & RCA Generator

---

## Python Version Management

### Current Version
- **Python**: 3.14.x (Latest stable)
- **Docker Image**: `python:3.14-slim`
- **Release Date**: October 7, 2025

### Version Policy
- **Development**: Use latest stable Python version (3.14.x)
- **Docker**: Always use `python:3.14-slim` base image
- **Compatibility**: Ensure all dependencies support Python 3.14

### Checking Python Version
Before implementing features or installing packages:
1. Verify Python 3.14 compatibility
2. Check package support for 3.14
3. Update requirements.txt with compatible versions

### Updating Python Version
When a new Python version is released:
1. Update Dockerfile FROM image
2. Update this AGENT.md file
3. Test all dependencies
4. Update docker-compose.yml if needed
5. Verify no breaking changes in code

---

## Docker Best Practices

### Base Image Selection
- **Primary**: `python:3.14-slim` (Debian-based, ~150MB)
- **Alternative**: `python:3.14-alpine` (if size critical)
- **Full**: `python:3.14` (if debugging tools needed)

### Security
- Run as non-root user (appuser)
- Use multi-stage builds for production
- Pin specific versions in requirements.txt
- Regular security updates

### Build Optimization
- Use .dockerignore to exclude unnecessary files
- Layer caching: Copy requirements.txt before app code
- Minimize layers by combining RUN commands
- Remove build dependencies after use

---

## Database Management

### PostgreSQL Version
- **Current**: PostgreSQL 15
- **Docker Image**: `postgres:15-alpine`

### Migration Workflow
1. Update SQLAlchemy models
2. Generate migration: `alembic revision --autogenerate -m "description"`
3. Review migration script
4. Apply: `alembic upgrade head`
5. Test rollback: `alembic downgrade -1`

### Environment Variables
- `DATABASE_URL`: Full PostgreSQL connection string
- `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`: Docker-compose defaults

---

## Code Organization

### Directory Structure
```
app/
├── main.py           # FastAPI app initialization
├── config.py         # Settings and configuration
├── database.py       # DB connection and sessions
├── dependencies.py   # FastAPI dependencies
├── core/            # Core utilities (exceptions, logger)
├── models/          # SQLAlchemy models
├── schemas/         # Pydantic schemas
├── routers/         # API route handlers
├── services/        # Business logic
└── tests/           # Test suite
```

### Naming Conventions
- **Files**: snake_case.py
- **Classes**: PascalCase
- **Functions/Variables**: snake_case
- **Constants**: UPPER_SNAKE_CASE

---

## API Development Guidelines

### Endpoint Design
- Use `/api/v1/` prefix for versioning
- RESTful resource naming (nouns, not verbs)
- HTTP methods: GET (read), POST (create), PUT/PATCH (update), DELETE (remove)
- Status codes: 200 OK, 201 Created, 400 Bad Request, 404 Not Found, 409 Conflict, 500 Error

### Response Format
```json
{
  "id": "uuid",
  "data": {},
  "message": "success",
  "timestamp": "2025-01-01T00:00:00Z"
}
```

### Error Handling
- Custom exceptions in `app/core/exceptions.py`
- Global exception handlers in `app/main.py`
- Consistent error response format
- Include error codes for programmatic handling

---

## Testing Strategy

### Unit Tests
- Test individual functions and classes
- Mock external dependencies (DB, AI services)
- Use pytest fixtures for setup/teardown

### Integration Tests
- Test API endpoints with TestClient
- Use test database (separate from dev/prod)
- Test full request/response cycles

### Test Commands
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest app/tests/test_logs.py
```

---

## Dependency Management

### Adding Dependencies
1. Add to `requirements.txt` with specific version
2. Run `pip install -r requirements.txt`
3. Test application
4. Update Docker image if needed

### Version Pinning
```
# Good
fastapi==0.115.0

# Avoid
fastapi>=0.115.0
```

### Key Dependencies
- **Web**: fastapi, uvicorn
- **Database**: sqlalchemy[asyncio], asyncpg, alembic
- **Validation**: pydantic, pydantic-settings
- **Testing**: pytest, pytest-asyncio, httpx

---

## AI Integration Guidelines

### Interface Design
- Abstract base class in `app/services/ai_analyzer.py`
- Mock implementation for development
- Easy to swap real AI provider (OpenAI, Anthropic, Opencode)

### Adding New AI Provider
1. Create new class implementing `AIAnalyzerInterface`
2. Add configuration to `app/config.py`
3. Update dependency injection in `app/dependencies.py`
4. Add tests
5. Document in README.md

---

## Deployment Checklist

### Pre-deployment
- [ ] All tests passing
- [ ] Database migrations tested
- [ ] Environment variables configured
- [ ] Docker image builds successfully
- [ ] Health check endpoint working
- [ ] API documentation accessible

### Production Deployment
1. Build Docker image: `docker build -t log-analyser:latest .`
2. Push to registry
3. Update docker-compose.yml with image tag
4. Deploy to server
5. Run migrations: `docker-compose exec api alembic upgrade head`
6. Verify health: `curl http://localhost:8000/health`

---

## Environment Management

### Development
```bash
DEBUG=True
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/loganalyser
```

### Production
```bash
DEBUG=False
DATABASE_URL=postgresql+asyncpg://user:pass@prod-db:5432/loganalyser
# Use strong passwords and secrets
```

### Local Setup
1. Copy `.env.example` to `.env`
2. Fill in your values
3. Never commit `.env` to git

---

## Performance Guidelines

### Database
- Use async database operations
- Add indexes for frequently queried fields
- Limit query results with pagination
- Use connection pooling

### API
- Keep response time < 2 seconds
- Use async/await for I/O operations
- Cache repeated calculations
- Compress large responses

### Docker
- Use slim images to reduce size
- Multi-stage builds for smaller production images
- Health checks for container orchestration

---

## Security Guidelines

### API Security
- Rate limiting on endpoints
- Input validation with Pydantic
- SQL injection prevention (use ORM)
- XSS protection (escape output)

### Docker Security
- Non-root user in containers
- Minimal base images
- No secrets in images
- Regular security updates

### Data Security
- Encrypt sensitive data at rest
- Use HTTPS in production
- Secure database connections
- Regular backups

---

## Documentation Standards

### Code Documentation
- Docstrings for all public functions/classes
- Type hints for function signatures
- Inline comments for complex logic
- README.md for setup instructions

### API Documentation
- Auto-generated with FastAPI
- Available at `/docs` (Swagger UI)
- Include request/response examples
- Document error responses

---

## Git Workflow

### Branching
- `main`: Production-ready code
- `develop`: Integration branch
- `feature/*`: New features
- `bugfix/*`: Bug fixes

### Commits
- Clear, descriptive commit messages
- Reference issue numbers if applicable
- Keep commits focused and atomic

### Pull Requests
- All tests must pass
- Code review required
- Update documentation if needed
- Squash and merge

---

## Monitoring and Logging

### Application Logging
- Use structured logging (JSON format)
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Include correlation IDs for tracing
- Log to stdout/stderr for Docker

### Health Checks
- `/health` endpoint for load balancers
- Database connectivity check
- External service checks (if any)
- Response time monitoring

### Metrics
- Request count and latency
- Error rates
- Database query performance
- Queue depth (if using async processing)

---

## Troubleshooting

### Common Issues

**Database connection failed**
- Check DATABASE_URL format
- Verify PostgreSQL is running
- Check network connectivity
- Review firewall rules

**Migration errors**
- Ensure models match database schema
- Check migration script syntax
- Run `alembic current` to see current version
- Use `alembic downgrade` if needed

**Docker build fails**
- Check Python version compatibility
- Verify requirements.txt syntax
- Ensure all files are present
- Check disk space

**API returns 500 errors**
- Check application logs
- Verify database connection
- Review recent code changes
- Test with debug mode enabled

---

## Resources

### Documentation
- FastAPI: https://fastapi.tiangolo.com
- SQLAlchemy: https://docs.sqlalchemy.org
- Alembic: https://alembic.sqlalchemy.org
- Pydantic: https://docs.pydantic.dev

### Tools
- Docker: https://docs.docker.com
- PostgreSQL: https://www.postgresql.org/docs
- pytest: https://docs.pytest.org

---

## Contact and Support

For issues or questions:
1. Check this AGENT.md file first
2. Review the IMPLEMENTATION_PLAN.md
3. Check API documentation at `/docs`
4. Review application logs
5. Create an issue with details

---

**Last Updated**: 2025
**Version**: MVP-1
**Python Version**: 3.14.x
**Status**: Active Development
