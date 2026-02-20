"""Application configuration settings."""

import os
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv

# Load environment variables from .env file (or .env.example if .env doesn't exist)
env_path = Path(__file__).parent.parent / ".env"
env_example_path = Path(__file__).parent.parent / ".env.example"

if env_path.exists():
    load_dotenv(dotenv_path=env_path)
elif env_example_path.exists():
    load_dotenv(dotenv_path=env_example_path)
else:
    load_dotenv()  # Try to load from default locations

# Database URL - Must be set in environment variable or .env file
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError(
        "DATABASE_URL environment variable is not set. "
        "Please set it before running the application."
    )

# Application settings
APP_NAME = os.getenv("APP_NAME", "Log Analysis & RCA Generator")
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "yes")
VERSION = os.getenv("VERSION", "1.0.0")

# CORS
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

# API
API_V1_PREFIX = os.getenv("API_V1_PREFIX", "/api/v1")

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG" if DEBUG else "INFO")

# Analysis settings
MAX_MESSAGE_PREVIEW_LENGTH = int(os.getenv("MAX_MESSAGE_PREVIEW_LENGTH", "500"))
DEFAULT_PAGE_SIZE = int(os.getenv("DEFAULT_PAGE_SIZE", "20"))
MAX_PAGE_SIZE = int(os.getenv("MAX_PAGE_SIZE", "100"))

# OpenCode server settings
# Set OPENCODE_SERVER_URL to enable the real OpenCode AI analyzer;
# otherwise the mock analyzer is used.
OPENCODE_SERVER_URL: Optional[str] = os.getenv("OPENCODE_SERVER_URL")  # e.g. http://localhost:4096
OPENCODE_PROVIDER_ID: Optional[str] = os.getenv("OPENCODE_PROVIDER_ID")  # e.g. anthropic, openai
OPENCODE_MODEL_ID: Optional[str] = os.getenv("OPENCODE_MODEL_ID")  # e.g. claude-sonnet-4-20250514
OPENCODE_SERVER_PASSWORD: Optional[str] = os.getenv("OPENCODE_SERVER_PASSWORD")
OPENCODE_SERVER_USERNAME: str = os.getenv("OPENCODE_SERVER_USERNAME", "opencode")
OPENCODE_TIMEOUT: float = float(os.getenv("OPENCODE_TIMEOUT", "60.0"))
