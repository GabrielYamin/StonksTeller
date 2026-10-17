import base64
import json

import pytest

from stonksteller.github import GitHubError, GitHubRepo


class FakeResponse:
    def __init__(self, status_code, payload=None, text=None):
        self.status_code = status_code
        self.text = text if text is not None else (json.dumps(payload) if payload is not None else "")
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def request(self, method, url, *, params, json, headers, timeout):
        self.calls.append((method, url, params, json, headers))
        return self.responses.pop(0)


def repo(*responses):
    session = FakeSession(responses)
    return GitHubRepo("ghtok", "o/r", session=session), session


def test_read_file_decodes_base64_and_returns_sha():
    content = base64.b64encode(b"AAPL\nSPY\n").decode()
    r, s = repo(FakeResponse(200, {"content": content[:4] + "\n" + content[4:], "sha": "sha1"}))
    assert r.read_file("stonks.txt", "stonks/discord") == ("AAPL\nSPY\n", "sha1")
    method, url, params, _, headers = s.calls[0]
    assert (method, url, params) == ("GET", "https://api.github.com/repos/o/r/contents/stonks.txt", {"ref": "stonks/discord"})
    assert headers["Authorization"] == "Bearer ghtok"


def test_write_file_sends_base64_on_the_branch_and_returns_new_sha():
    r, s = repo(FakeResponse(200, {"content": {"sha": "sha2"}}))
    assert r.write_file("stonks.txt", "stonks/discord", "AAPL\n", "sha1", "Add AAPL") == "sha2"
    body = s.calls[0][3]
    assert body == {"message": "Add AAPL", "content": base64.b64encode(b"AAPL\n").decode(),
                    "sha": "sha1", "branch": "stonks/discord"}


def test_branch_sha_is_none_on_404():
    r, _ = repo(FakeResponse(404, text='{"message": "Not Found"}'))
    assert r.branch_sha("stonks/discord") is None


def test_open_pull_filters_by_owner_head_and_returns_first():
    r, s = repo(FakeResponse(200, [{"number": 7, "html_url": "u"}]))
    assert r.open_pull("stonks/discord") == {"number": 7, "html_url": "u"}
    assert s.calls[0][2] == {"head": "o:stonks/discord", "state": "open"}


def test_create_pull_payload():
    r, s = repo(FakeResponse(201, {"number": 8, "html_url": "u8"}))
    assert r.create_pull("stonks/discord", "main", "T", "B")["html_url"] == "u8"
    assert s.calls[0][3] == {"title": "T", "head": "stonks/discord", "base": "main", "body": "B"}


def test_errors_carry_status_and_body_but_not_the_token():
    r, _ = repo(FakeResponse(403, text='{"message": "Resource not accessible by integration"}'))
    with pytest.raises(GitHubError, match="403.*Resource not accessible") as exc:
        r.default_branch()
    assert "ghtok" not in str(exc.value)
