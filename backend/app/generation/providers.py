"""Shared plumbing for calling flaky external generators: errors, cooldowns, deadlines."""
import asyncio
import re
import time
from typing import Any, Callable

import httpx

from . import config


class ProviderError(Exception):
    """A provider failed for this request; the next provider in the chain may still work."""

    def __init__(self, provider: str, message: str, *, quota: bool = False):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.message = message
        self.quota = quota


class ProviderTimeout(ProviderError):
    pass


_cooldown_until: dict[str, float] = {}
_cooldown_reason: dict[str, str] = {}


def cooling_down(provider: str) -> str | None:
    """Return the reason a provider is being skipped, or None if it's usable."""
    if _cooldown_until.get(provider, 0) > time.monotonic():
        return _cooldown_reason.get(provider, "cooling down")
    return None


def start_cooldown(provider: str, reason: str, seconds: float = config.PROVIDER_COOLDOWN_S) -> None:
    _cooldown_until[provider] = time.monotonic() + seconds
    _cooldown_reason[provider] = reason


def looks_like_quota(message: str) -> bool:
    return bool(re.search(r"quota|RESOURCE_EXHAUSTED|429|rate limit|credits|402|payment", message, re.I))


async def run_blocking(fn: Callable[[float], Any], timeout: float, provider: str) -> Any:
    """Run fn(deadline) in a worker thread with a hard wall-clock timeout.

    fn gets an absolute time.monotonic() deadline so it can bound its own waits (e.g.
    gradio Job.result(timeout=...)) and cancel remote work cleanly. The outer wait_for
    is the backstop in case a library call ignores it.
    """
    deadline = time.monotonic() + timeout
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, deadline), timeout + 2)
    except (asyncio.TimeoutError, TimeoutError):
        raise ProviderTimeout(provider, f"timed out after {timeout:.0f}s") from None


_space_stage_cache: dict[str, tuple[float, str]] = {}


def hf_space_stage(space: str) -> str:
    """Runtime stage of an HF Space (RUNNING, RUNTIME_ERROR, SLEEPING, ...), cached 5 min."""
    now = time.monotonic()
    hit = _space_stage_cache.get(space)
    if hit and now - hit[0] < 300:
        return hit[1]
    headers = {"Authorization": f"Bearer {config.HF_TOKEN}"} if config.HF_TOKEN else {}
    try:
        r = httpx.get(f"https://huggingface.co/api/spaces/{space}", headers=headers, timeout=10)
        stage = (r.json().get("runtime") or {}).get("stage") or f"HTTP_{r.status_code}"
    except Exception as e:  # network trouble: don't block, let the real call decide
        stage = f"UNKNOWN ({type(e).__name__})"
    _space_stage_cache[space] = (now, stage)
    return stage
