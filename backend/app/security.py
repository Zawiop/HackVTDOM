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


async def require_admin(x_admin_token: str = Header(default="")) -> None:
    """No-op when ADMIN_TOKEN is unset (local dev); enforced once it is.

    Constant-time comparison so response timing can't be used to guess the
    token a character at a time.
    """
    settings = get_settings()
    if not settings.admin_token:
        return
    if not hmac.compare_digest(x_admin_token, settings.admin_token):
        raise HTTPException(status_code=401, detail="missing or incorrect X-Admin-Token header")
