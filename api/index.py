"""Vercel Python Function entrypoint for the TESSERA HTTP handler.

The application handler subclasses BaseHTTPRequestHandler, which is the native
Vercel Python Function contract. This keeps the local and hosted API behavior
identical while Vercel provides the HTTP lifecycle.
"""

from tessera.server import Handler


class handler(Handler):
    """Explicit Vercel entrypoint discovered by the Python runtime."""


__all__ = ["handler"]
