"""
Middleware Components

Provides request processing middleware for logging, rate limiting, and correlation IDs.
"""

import time
import uuid
from collections import defaultdict
from typing import Callable, Dict, Optional

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.security import validate_access_token
from app.core.logging import get_logger, set_correlation_id

logger = get_logger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Add correlation ID to each request for tracing."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Get correlation ID from header or generate new one
        correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
        set_correlation_id(correlation_id)
        
        # Store in request state for access in handlers
        request.state.correlation_id = correlation_id
        
        response = await call_next(request)
        
        # Add correlation ID to response headers
        response.headers["X-Correlation-ID"] = correlation_id
        
        return response


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log request and response details."""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()
        
        # Log request
        logger.info(
            "Request started",
            method=request.method,
            path=request.url.path,
            query=str(request.query_params),
            client_ip=request.client.host if request.client else None,
        )
        
        response = await call_next(request)
        
        # Calculate duration
        duration_ms = (time.perf_counter() - start_time) * 1000
        
        # Log response
        logger.info(
            "Request completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(duration_ms, 2),
        )
        
        # Add timing header
        response.headers["X-Response-Time-Ms"] = str(round(duration_ms, 2))
        
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    In-memory rate limiting middleware.
    
    Implements a simple sliding window counter per user or client IP address.
    Can be replaced with Redis-based implementation for distributed systems.
    """
    
    def __init__(self, app: Callable) -> None:
        super().__init__(app)
        self.request_counts: Dict[str, list] = defaultdict(list)
        self.auth_request_counts: Dict[str, list] = defaultdict(list)
    
    def _clean_old_requests(self, timestamps: list, window_seconds: int) -> list:
        """Remove timestamps outside the current window."""
        cutoff = time.time() - window_seconds
        return [ts for ts in timestamps if ts > cutoff]

    def _get_forwarded_client_ip(self, request: Request) -> str:
        """Resolve real client IP behind proxies such as Render."""
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()

        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip.strip()

        return request.client.host if request.client else "unknown"

    def _get_user_key(self, request: Request) -> Optional[str]:
        """Use authenticated user ID as the limiter key when a valid token exists."""
        auth_header = request.headers.get("authorization", "")
        scheme, _, token = auth_header.partition(" ")

        if scheme.lower() != "bearer" or not token:
            return None

        try:
            payload = validate_access_token(token)
        except Exception:
            return None

        user_id = payload.get("sub")
        return f"user:{user_id}" if user_id else None

    def _get_rate_limit_key(self, request: Request) -> str:
        """Prefer per-user limits, falling back to per-client IP for anonymous traffic."""
        user_key = self._get_user_key(request)
        if user_key:
            return user_key

        return f"ip:{self._get_forwarded_client_ip(request)}"

    def _is_exempt_path(self, request: Request) -> bool:
        """Skip rate limiting for browser preflight, static assets, and health checks."""
        path = request.url.path
        exempt_prefixes = (
            "/css/",
            "/js/",
            "/health",
            "/ready",
            "/favicon.ico",
            f"{settings.API_V1_PREFIX}/openapi.json",
            f"{settings.API_V1_PREFIX}/docs",
            f"{settings.API_V1_PREFIX}/redoc",
        )
        return request.method == "OPTIONS" or path == "/" or path.startswith(exempt_prefixes)
    
    def _is_rate_limited(
        self,
        key: str,
        is_auth_endpoint: bool,
    ) -> bool:
        """Check if the client has exceeded rate limits."""
        current_time = time.time()
        window_seconds = 60  # 1 minute window
        
        if is_auth_endpoint:
            # Stricter limit for auth endpoints
            self.auth_request_counts[key] = self._clean_old_requests(
                self.auth_request_counts[key], window_seconds
            )
            
            if len(self.auth_request_counts[key]) >= settings.RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE:
                return True
            
            self.auth_request_counts[key].append(current_time)
        else:
            # General rate limit
            self.request_counts[key] = self._clean_old_requests(
                self.request_counts[key], window_seconds
            )
            
            if len(self.request_counts[key]) >= settings.RATE_LIMIT_REQUESTS_PER_MINUTE:
                return True
            
            self.request_counts[key].append(current_time)
        
        return False
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if self._is_exempt_path(request):
            return await call_next(request)

        rate_limit_key = self._get_rate_limit_key(request)
        is_auth_endpoint = request.url.path.startswith(f"{settings.API_V1_PREFIX}/auth")
        
        if self._is_rate_limited(rate_limit_key, is_auth_endpoint):
            logger.warning(
                "Rate limit exceeded",
                rate_limit_key=rate_limit_key,
                path=request.url.path,
            )
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": "60"},
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "Rate limit exceeded. Please try again later.",
                        "details": {
                            "window_seconds": 60,
                            "limit": (
                                settings.RATE_LIMIT_AUTH_REQUESTS_PER_MINUTE
                                if is_auth_endpoint
                                else settings.RATE_LIMIT_REQUESTS_PER_MINUTE
                            ),
                        },
                        "correlation_id": getattr(request.state, "correlation_id", None),
                    }
                },
            )
        
        return await call_next(request)
