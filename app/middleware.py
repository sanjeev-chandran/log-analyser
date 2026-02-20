"""Application middleware.

``RequestIDMiddleware`` generates (or accepts) a unique request ID per
HTTP request, stores it in a ``ContextVar`` so every log line in the
call chain includes it, and echoes it back in the ``X-Request-ID``
response header.
"""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.request_context import set_request_id, reset_request_id

_REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique ``request_id`` to every request.

    Behaviour:
    - If the caller sends an ``X-Request-ID`` header, we **reuse** it
      (useful when an API gateway or load balancer already assigned one).
    - Otherwise we generate a new UUID-4.
    - The ID is stored in a ``ContextVar`` so the JSON log formatter can
      read it automatically — no manual ``extra={"request_id": ...}``
      needed anywhere.
    - The same ID is echoed back in the ``X-Request-ID`` response header
      so the caller can correlate their request with server-side logs.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Accept from caller or generate
        request_id = request.headers.get(_REQUEST_ID_HEADER) or str(uuid.uuid4())

        # Store in ContextVar for the duration of this request
        token = set_request_id(request_id)
        try:
            response: Response = await call_next(request)
            response.headers[_REQUEST_ID_HEADER] = request_id
            return response
        finally:
            reset_request_id(token)
