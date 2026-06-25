# ABOUTME: Composition root + request dependencies — binds adapters to ports and resolves a session.
# ABOUTME: Keeps wiring and the session cookie/middleware out of the route handlers in main.py.
"""Where the ports get their concrete adapters, and how a request finds its session.

This is the app's composition root: the single place that picks which adapter
stands behind each port (the mock today, a live backend later). Routes never name
a concrete adapter — they take `get_application` / `get_store` and a `session_id`,
so swapping an adapter is a one-line change here.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import Request

from app.domain import Application
from app.providers import ApplicationProvider
from app.providers.fixtures import FixtureProvider
from app.selections import InMemorySelectionStore, SelectionStore

SESSION_COOKIE = "cj_session"

# The adapters bound to the ports for this process. Swap either line to change
# the backing implementation; nothing downstream needs to know.
provider: ApplicationProvider = FixtureProvider()
store: SelectionStore = InMemorySelectionStore()


def get_application() -> Application:
    return provider.get_application()


def get_store() -> SelectionStore:
    return store


async def ensure_session(request: Request, call_next):
    """Give every browser a stable session id so picks are scoped to one run.

    Done in middleware (not a route dependency) so the cookie is set on the
    outgoing response no matter what type a route returns — including the
    RedirectResponses the curate flow leans on.
    """
    sid = request.cookies.get(SESSION_COOKIE)
    is_new = sid is None
    if is_new:
        sid = uuid4().hex
    request.state.session_id = sid
    response = await call_next(request)
    if is_new:
        response.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="lax")
    return response


def session_id(request: Request) -> str:
    return request.state.session_id
