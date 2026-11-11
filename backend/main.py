"""
Vercel application entrypoint for FastAPI.
Exposes the FastAPI instance `app` from `app.main`.
"""

from app.main import app

__all__ = ["app"]
