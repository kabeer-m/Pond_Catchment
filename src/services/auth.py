"""
auth.py
-------
Lightweight API-key authentication for the write/compute endpoints
(analysis is CPU-expensive, so an unauthenticated deployment is an easy
denial-of-service target).

Design notes (CSD: Authentication / Authorization):
- Deliberately simple: a shared secret in the POND_API_KEY environment
  variable, sent by clients as the `X-API-Key` header. This is the
  right amount of security for an internal tool used by a handful of
  village administrators/field officers, not a multi-tenant public
  product -- a heavier scheme (OAuth2, per-user JWTs) would be over-
  engineering for this assignment's scope, but is a natural extension
  if the system grows beyond a single trusted organization.
- If POND_API_KEY is unset, auth is a no-op (open access). This keeps
  local development and `pytest` frictionless while still giving a real
  deployment environment a one-line way to lock things down.
- Implemented as a decorator so it's opt-in per route and never mixed
  into the analysis logic in app.py's request handlers.
"""

import os
from functools import wraps

from flask import jsonify, request

API_KEY_ENV_VAR = "POND_API_KEY"
API_KEY_HEADER = "X-API-Key"


def require_api_key(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        expected = os.environ.get(API_KEY_ENV_VAR)
        if not expected:
            # No key configured -> auth disabled (e.g. local dev).
            return view_func(*args, **kwargs)
        provided = request.headers.get(API_KEY_HEADER)
        if provided != expected:
            return jsonify(error="Missing or invalid API key."), 401
        return view_func(*args, **kwargs)

    return wrapped
