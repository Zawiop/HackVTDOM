"""Guards the small set of destructive routes: per-row/address delete, world reset.

Everything else in the API stays open — this is a hackathon demo, not a
multi-tenant product, and gating reads or generation would only add friction
for no real benefit. The one real risk is data loss: once the API has a
public URL, `DELETE /world` is discoverable by anyone who opens `/docs`, and
its `confirm=yes` query string is documented right there — the UI's two-step
confirmation is a client-side nicety, not a server-side control.
"""

import hmac

from fastapi import Header, HTTPException

from .config import get_settings


def check_admin_token(token: str) -> None:
    """No-op when ADMIN_TOKEN is unset (local dev); enforced once it is.

    Constant-time comparison so response timing can't be used to guess the
    token a character at a time. Exposed separately from `require_admin` so a
    route that is only *conditionally* destructive — `/api/world/import` and
    `/api/world/seed` are safe in `mode=merge`, as destructive as a full reset
    in `mode=replace` — can check it inline instead of gating the whole route.
    """
    settings = get_settings()
    if not settings.admin_token:
        return
    if not hmac.compare_digest(token, settings.admin_token):
        raise HTTPException(status_code=401, detail="missing or incorrect X-Admin-Token header")


async def require_admin(x_admin_token: str = Header(default="")) -> None:
    check_admin_token(x_admin_token)
