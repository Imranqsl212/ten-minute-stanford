from __future__ import annotations

import hashlib
import json
import random
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .config import USER_AGENT


class FetchError(RuntimeError):
    """Raised when a public source cannot be fetched after retries."""


def looks_like_authentication_page(text: str, final_url: str = "") -> bool:
    """Reject login interstitials before they can silently poison the cache."""
    hostname = (urlparse(final_url).hostname or "").casefold()
    lowered = text.casefold()
    return hostname == "login.stanford.edu" or (
        "stanford login" in lowered
        and (
            "loading login session information" in lowered
            or "saml2/redirect/sso" in lowered
        )
    )


class CachedFetcher:
    def __init__(
        self,
        *,
        min_delay_seconds: float = 0.2,
        timeout_seconds: float = 45.0,
        retries: int = 4,
    ) -> None:
        self.min_delay_seconds = min_delay_seconds
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self._last_request_at = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.session.cookies.set("jsenabled", "1")

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_delay_seconds:
            time.sleep(self.min_delay_seconds - elapsed)

    def get_text(
        self,
        url: str,
        cache_path: Path,
        *,
        params: dict[str, Any] | None = None,
        refresh: bool = False,
    ) -> str:
        if cache_path.exists() and not refresh:
            cached = cache_path.read_text(encoding="utf-8")
            if not looks_like_authentication_page(cached):
                return cached

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        error: Exception | None = None
        for attempt in range(self.retries):
            try:
                self._wait()
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout_seconds,
                    allow_redirects=True,
                )
                self._last_request_at = time.monotonic()
                response.raise_for_status()
                text = response.text
                if not text.strip():
                    raise FetchError(f"Empty response from {response.url}")
                if looks_like_authentication_page(text, response.url):
                    raise FetchError(
                        f"Authentication page returned instead of public data: {response.url}"
                    )
                cache_path.write_text(text, encoding="utf-8")
                self._write_metadata(cache_path, response.url, response.status_code, params)
                return text
            except (requests.RequestException, FetchError) as exc:
                error = exc
                if attempt + 1 < self.retries:
                    time.sleep((2**attempt) + random.random())
        raise FetchError(f"Failed to fetch {url}: {error}")

    def get_json(
        self,
        url: str,
        cache_path: Path,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        refresh: bool = False,
    ) -> dict[str, Any]:
        if cache_path.exists() and not refresh:
            return json.loads(cache_path.read_text(encoding="utf-8"))

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        error: Exception | None = None
        for attempt in range(self.retries):
            try:
                self._wait()
                if data is None:
                    response = self.session.get(
                        url,
                        params=params,
                        timeout=self.timeout_seconds,
                    )
                else:
                    response = self.session.post(
                        url,
                        params=params,
                        data=data,
                        timeout=max(self.timeout_seconds, 180),
                    )
                self._last_request_at = time.monotonic()
                response.raise_for_status()
                payload = response.json()
                cache_path.write_text(
                    json.dumps(payload, ensure_ascii=True), encoding="utf-8"
                )
                self._write_metadata(cache_path, response.url, response.status_code, params)
                return payload
            except (requests.RequestException, ValueError) as exc:
                error = exc
                if attempt + 1 < self.retries:
                    time.sleep((2**attempt) + random.random())
        raise FetchError(f"Failed to fetch JSON from {url}: {error}")

    @staticmethod
    def _write_metadata(
        cache_path: Path,
        source_url: str,
        status_code: int,
        params: dict[str, Any] | None,
    ) -> None:
        digest = hashlib.sha256(cache_path.read_bytes()).hexdigest()
        metadata = {
            "source_url": source_url,
            "status_code": status_code,
            "retrieved_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sha256": digest,
            "params": params or {},
        }
        cache_path.with_suffix(cache_path.suffix + ".meta.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
        )
