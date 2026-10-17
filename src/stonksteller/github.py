"""Minimal GitHub REST client: a branch, a file commit, a pull request."""
from __future__ import annotations

import base64

import requests

from . import __version__

API_BASE = "https://api.github.com"
USER_AGENT = f"StonksTeller (https://github.com/GabrielYamin/StonksTeller, {__version__})"
TIMEOUT = 15.0


class GitHubError(Exception):
    """GitHub did not accept a request."""


class GitHubRepo:
    def __init__(self, token: str, repo: str, *, session=None):
        self.repo = repo                       # "owner/name"
        self.owner = repo.split("/", 1)[0]
        self._session = session if session is not None else requests.Session()
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }

    def default_branch(self) -> str:
        return self._request("GET", f"/repos/{self.repo}")["default_branch"]

    def branch_sha(self, branch: str) -> str | None:
        data = self._request("GET", f"/repos/{self.repo}/git/ref/heads/{branch}", allow_404=True)
        return None if data is None else data["object"]["sha"]

    def create_branch(self, branch: str, sha: str) -> None:
        self._request("POST", f"/repos/{self.repo}/git/refs", json={"ref": f"refs/heads/{branch}", "sha": sha})

    def delete_branch(self, branch: str) -> None:
        self._request("DELETE", f"/repos/{self.repo}/git/refs/heads/{branch}", allow_404=True)

    def read_file(self, path: str, ref: str) -> tuple[str, str]:
        """Return (text, blob sha) of a file on a branch."""
        data = self._request("GET", f"/repos/{self.repo}/contents/{path}", params={"ref": ref})
        return base64.b64decode(data["content"]).decode("utf-8"), data["sha"]

    def write_file(self, path: str, branch: str, text: str, sha: str, message: str) -> str:
        """Commit new contents for a file on a branch; returns the new blob sha."""
        data = self._request("PUT", f"/repos/{self.repo}/contents/{path}", json={
            "message": message,
            "content": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            "sha": sha,
            "branch": branch,
        })
        return data["content"]["sha"]

    def open_pull(self, head: str) -> dict | None:
        pulls = self._request("GET", f"/repos/{self.repo}/pulls",
                              params={"head": f"{self.owner}:{head}", "state": "open"})
        return pulls[0] if pulls else None

    def create_pull(self, head: str, base: str, title: str, body: str) -> dict:
        return self._request("POST", f"/repos/{self.repo}/pulls",
                             json={"title": title, "head": head, "base": base, "body": body})

    def update_pull_body(self, number: int, body: str) -> None:
        self._request("PATCH", f"/repos/{self.repo}/pulls/{number}", json={"body": body})

    def _request(self, method: str, path: str, *, params=None, json=None, allow_404: bool = False):
        try:
            response = self._session.request(method, API_BASE + path, params=params, json=json,
                                             headers=self._headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise GitHubError(f"request to GitHub failed: {type(exc).__name__}") from None
        if response.status_code == 404 and allow_404:
            return None
        if not 200 <= response.status_code < 300:
            raise GitHubError(f"GitHub returned {response.status_code}: {response.text[:500]}")
        if response.status_code == 204 or not response.text:
            return None
        return response.json()
