"""Minimal Facebook Graph API client for publishing to a Page."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

GRAPH = "https://graph.facebook.com"


class FacebookError(RuntimeError):
    def __init__(self, message: str, code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.code = code
        self.payload = payload


# Graph API error codes that mean the token is expired, revoked or lacks permissions.
_TOKEN_CODES = {102, 190, 200, 10}


def _explain(code: int | None, message: str) -> str:
    if code in _TOKEN_CODES:
        return (
            f"{message}\nToken problem: create a new Page Access Token with the "
            "pages_manage_posts and pages_read_engagement permissions (see README)."
        )
    if code in {4, 17, 32, 613}:
        return f"{message}\nRate limited by Facebook. Try again later."
    if code == 368:
        return f"{message}\nFacebook blocked this post as possibly abusive. Review the content."
    return message


class FacebookPage:
    def __init__(
        self,
        page_id: str,
        token: str,
        version: str = "v26.0",
        session: requests.Session | None = None,
        timeout: float = 60.0,
    ):
        if not page_id or not token:
            raise FacebookError("FB_PAGE_ID and FB_PAGE_ACCESS_TOKEN must both be set")
        self.page_id = page_id
        self.token = token
        self.base = f"{GRAPH}/{version}"
        self.http = session or requests.Session()
        self.timeout = timeout

    def _request(self, method: str, path: str, *, data: dict | None = None, params: dict | None = None, files: dict | None = None) -> dict:
        url = f"{self.base}/{path.lstrip('/')}"
        if method == "GET":
            params = {**(params or {}), "access_token": self.token}
        else:
            data = {**(data or {}), "access_token": self.token}
        resp = self.http.request(method, url, params=params, data=data, files=files, timeout=self.timeout)
        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text}
        if resp.status_code >= 400 or (isinstance(body, dict) and "error" in body):
            err = body.get("error", {}) if isinstance(body, dict) else {}
            code = err.get("code")
            message = err.get("message") or f"HTTP {resp.status_code}: {resp.text[:300]}"
            raise FacebookError(_explain(code, message), code=code, payload=body)
        return body

    # ------------------------------------------------------------------ reads
    def info(self) -> dict:
        """Basic Page info; also proves the token works for this Page."""
        return self._request("GET", self.page_id, params={"fields": "id,name,fan_count,link"})

    def permalink(self, object_id: str) -> str | None:
        try:
            return self._request("GET", object_id, params={"fields": "permalink_url"}).get("permalink_url")
        except FacebookError:
            return None

    # ----------------------------------------------------------------- writes
    def post_text(self, message: str) -> str:
        """Publish a text post to the Page feed. Returns the post id."""
        body = self._request("POST", f"{self.page_id}/feed", data={"message": message})
        return body["id"]

    def post_photo(self, image_path: Path, message: str) -> str:
        """Publish a photo with a caption. Returns the feed post id (falls back to the photo id)."""
        with Path(image_path).open("rb") as fh:
            body = self._request(
                "POST",
                f"{self.page_id}/photos",
                data={"message": message, "published": "true"},
                files={"source": (Path(image_path).name, fh, "image/png")},
            )
        return body.get("post_id") or body["id"]


def exchange_for_page_tokens(app_id: str, app_secret: str, short_user_token: str, version: str = "v26.0", session: requests.Session | None = None) -> list[dict]:
    """Turn a short-lived user token into long-lived Page tokens.

    A Page token obtained from a long-lived user token has no expiry date
    (it stops working only if the password changes or the app loses access).
    """
    http = session or requests.Session()
    base = f"{GRAPH}/{version}"
    resp = http.get(
        f"{base}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_user_token,
        },
        timeout=60,
    )
    data = resp.json()
    if "error" in data:
        raise FacebookError(data["error"].get("message", str(data)), code=data["error"].get("code"), payload=data)
    long_user_token = data["access_token"]
    resp = http.get(
        f"{base}/me/accounts",
        params={"fields": "id,name,access_token,tasks", "access_token": long_user_token, "limit": 100},
        timeout=60,
    )
    data = resp.json()
    if "error" in data:
        raise FacebookError(data["error"].get("message", str(data)), code=data["error"].get("code"), payload=data)
    return data.get("data", [])
