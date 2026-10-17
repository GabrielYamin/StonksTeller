"""The one call to Discord: execute a channel webhook."""
from __future__ import annotations

import logging
import time
from typing import Callable
from urllib.parse import quote, urlsplit

import requests

from . import __version__

API_BASE = "https://discord.com/api/v10"
USER_AGENT = f"StonksTeller (https://github.com/GabrielYamin/StonksTeller, {__version__})"
TIMEOUT = 15.0
WEBHOOK_HOSTS = ("discord.com", "discordapp.com", "ptb.discord.com", "canary.discord.com")
log = logging.getLogger(__name__)


class DiscordError(Exception):
    """Discord did not accept the message."""


def is_webhook_url(url: str) -> bool:
    """True for https://discord.com/api/webhooks/<id>/<token> (and Discord's other hosts)."""
    parts = urlsplit(url)
    segments = [segment for segment in parts.path.split("/") if segment]
    return (
        parts.scheme == "https"
        and parts.netloc in WEBHOOK_HOSTS
        and segments[:2] == ["api", "webhooks"]
        and len(segments) >= 4
    )


def post_message(
    webhook_url: str,
    embeds: list[dict],
    *,
    session=None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """POST the embeds to the webhook; retries once on 429 (honouring retry_after) or 5xx."""
    if session is None:
        session = requests.Session()
    headers = {"User-Agent": USER_AGENT}
    payload = {"embeds": list(embeds)}
    params = {"wait": "true"}  # make Discord report validation errors instead of a bare 204

    response = _post(session, webhook_url, payload, headers, params)
    if _ok(response):
        return
    if response.status_code == 429:
        wait = _retry_after(response)
        log.warning("Discord rate limited; retrying in %.1fs", wait)
        sleep(wait)
    elif response.status_code >= 500:
        log.warning("Discord returned %s; retrying in 2s", response.status_code)
        sleep(2.0)
    else:
        raise DiscordError(_describe(response))

    response = _post(session, webhook_url, payload, headers, params)
    if not _ok(response):
        raise DiscordError(_describe(response))


def _post(session, url: str, payload: dict, headers: dict, params: dict):
    try:
        return session.post(url, json=payload, headers=headers, params=params, timeout=TIMEOUT)
    except requests.RequestException as exc:
        # The webhook URL is the secret, and requests puts URLs in its messages: report the class only.
        raise DiscordError(f"request to Discord failed: {type(exc).__name__}") from None


def _ok(response) -> bool:
    return 200 <= response.status_code < 300


def _describe(response) -> str:
    return f"Discord returned {response.status_code}: {response.text[:500]}"


def _retry_after(response) -> float:
    try:
        return float(response.json()["retry_after"])
    except Exception:  # noqa: BLE001 - fall through to the header
        pass
    try:
        return float(response.headers.get("Retry-After"))
    except (TypeError, ValueError):
        return 1.0


class BotClient:
    """Minimal Discord REST client for a bot token: read a channel, react, reply."""

    def __init__(self, token: str, *, session=None, sleep: Callable[[float], None] = time.sleep):
        self._session = session if session is not None else requests.Session()
        self._headers = {"Authorization": f"Bot {token}", "User-Agent": USER_AGENT}
        self._sleep = sleep

    def list_messages(self, channel_id: str, limit: int = 50) -> list[dict]:
        """Recent messages, newest first, as Discord returns them."""
        return self._request("GET", f"/channels/{channel_id}/messages", params={"limit": str(limit)}) or []

    def add_reaction(self, channel_id: str, message_id: str, emoji: str) -> None:
        self._request("PUT", f"/channels/{channel_id}/messages/{message_id}/reactions/{quote(emoji)}/@me")

    def reply(self, channel_id: str, message_id: str, content: str) -> None:
        self._request("POST", f"/channels/{channel_id}/messages", json={
            "content": content,
            "message_reference": {"message_id": message_id},
            "allowed_mentions": {"parse": []},
        })

    def guild_id(self, channel_id: str) -> str | None:
        channel = self._request("GET", f"/channels/{channel_id}") or {}
        return channel.get("guild_id")

    def _request(self, method: str, path: str, *, params=None, json=None):
        response = self._send(method, path, params, json)
        if response.status_code == 429:
            wait = _retry_after(response)
            log.warning("Discord rate limited; retrying in %.1fs", wait)
            self._sleep(wait)
            response = self._send(method, path, params, json)
        if not _ok(response):
            raise DiscordError(_describe(response))
        if response.status_code == 204 or not response.text:
            return None
        return response.json()

    def _send(self, method: str, path: str, params, json):
        try:
            return self._session.request(method, API_BASE + path, params=params, json=json,
                                         headers=self._headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise DiscordError(f"request to Discord failed: {type(exc).__name__}") from None
