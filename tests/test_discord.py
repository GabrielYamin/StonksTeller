import json

import pytest
import requests

from stonksteller.discord import DiscordError, is_webhook_url, post_message

URL = "https://discord.com/api/webhooks/123/SECRET-token"


class FakeResponse:
    def __init__(self, status_code, text="", retry_after=None):
        self.status_code, self.text = status_code, text
        self.headers = {"Retry-After": retry_after} if retry_after else {}

    def json(self):
        return json.loads(self.text)


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def post(self, url, *, json, headers, params, timeout):
        self.calls.append((url, json, headers, params, timeout))
        return self.responses.pop(0)


def post(session, embeds=None):
    slept = []
    post_message(URL, embeds or [], session=session, sleep=slept.append)
    return slept


@pytest.mark.parametrize("url, expected", [
    (URL, True),
    ("https://ptb.discord.com/api/webhooks/123/tok", True),
    ("http://discord.com/api/webhooks/123/tok", False),        # not https
    ("https://example.com/api/webhooks/123/tok", False),       # wrong host
    ("https://discord.com/api/webhooks/123", False),           # token missing
    ("https://discord.com/api/channels/123/messages", False),  # not a webhook path
    ("MTIz.abc.def", False),                                   # a bot token, not a URL
])
def test_is_webhook_url(url, expected):
    assert is_webhook_url(url) is expected


def test_posts_embeds_to_the_webhook_and_waits_for_the_result():
    s = FakeSession([FakeResponse(200)])
    post(s, [{"title": "x"}])
    url, body, headers, params, timeout = s.calls[0]
    assert url == URL
    assert body == {"embeds": [{"title": "x"}]}
    assert params == {"wait": "true"}
    assert "Authorization" not in headers
    assert timeout > 0


def test_retries_once_on_429_honoring_retry_after():
    s = FakeSession([FakeResponse(429, '{"retry_after": 1.5}', retry_after="1.5"), FakeResponse(200)])
    assert post(s) == [1.5]
    assert len(s.calls) == 2


def test_retries_once_on_5xx():
    s = FakeSession([FakeResponse(502, "bad gateway"), FakeResponse(200)])
    post(s)
    assert len(s.calls) == 2


def test_raises_after_failed_retry():
    s = FakeSession([FakeResponse(500, "boom"), FakeResponse(500, "boom")])
    with pytest.raises(DiscordError, match="500"):
        post(s)


def test_other_4xx_raises_without_retry_and_without_the_secret():
    s = FakeSession([FakeResponse(404, '{"message": "Unknown Webhook"}')])
    with pytest.raises(DiscordError, match="Unknown Webhook") as exc:
        post(s)
    assert len(s.calls) == 1
    assert "SECRET" not in str(exc.value)


def test_connection_errors_never_mention_the_url():
    class Exploding:
        def post(self, url, **kwargs):
            raise requests.ConnectionError(f"Max retries exceeded with url: {url}")

    with pytest.raises(DiscordError) as exc:
        post_message(URL, [], session=Exploding(), sleep=lambda _: None)
    assert "ConnectionError" in str(exc.value)
    assert "SECRET" not in str(exc.value)
    assert exc.value.__cause__ is None and exc.value.__suppress_context__


# ---- BotClient ----
from stonksteller.discord import BotClient  # noqa: E402


class FakeApiSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def request(self, method, url, *, params, json, headers, timeout):
        self.calls.append((method, url, params, json, headers))
        return self.responses.pop(0)


def test_bot_lists_messages_with_bot_auth_and_limit():
    s = FakeApiSession([FakeResponse(200, '[{"id": "1"}]')])
    assert BotClient("bottok", session=s).list_messages("123") == [{"id": "1"}]
    method, url, params, _, headers = s.calls[0]
    assert (method, url, params) == ("GET", "https://discord.com/api/v10/channels/123/messages", {"limit": "50"})
    assert headers["Authorization"] == "Bot bottok"


def test_bot_reaction_url_encodes_the_emoji():
    s = FakeApiSession([FakeResponse(204)])
    BotClient("bottok", session=s).add_reaction("123", "9", "✅")
    assert s.calls[0][:2] == ("PUT", "https://discord.com/api/v10/channels/123/messages/9/reactions/%E2%9C%85/@me")


def test_bot_reply_references_the_message_and_disables_mentions():
    s = FakeApiSession([FakeResponse(200, '{"id": "10"}')])
    BotClient("bottok", session=s).reply("123", "9", "hi")
    assert s.calls[0][3] == {"content": "hi", "message_reference": {"message_id": "9"},
                             "allowed_mentions": {"parse": []}}


def test_bot_retries_once_on_429_then_raises_without_token():
    s = FakeApiSession([FakeResponse(429, '{"retry_after": 0.5}'), FakeResponse(403, '{"message": "Missing Access"}')])
    slept = []
    with pytest.raises(DiscordError, match="Missing Access") as exc:
        BotClient("bottok", session=s, sleep=slept.append).list_messages("123")
    assert slept == [0.5] and "bottok" not in str(exc.value)
