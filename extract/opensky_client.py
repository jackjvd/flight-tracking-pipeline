"""HTTP client for the OpenSky Network REST API."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

import requests

from extract.config import BoundingBox, Settings
from extract.models import StatesSnapshot

log = logging.getLogger(__name__)

API_URL = "https://opensky-network.org/api"
TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
RETRY_STATUSES = {429, 500, 502, 503, 504}
TOKEN_REFRESH_MARGIN = 60  # seconds before expiry to fetch a new token


class OpenSkyError(RuntimeError):
    """Raised when the API cannot be reached or returns an unusable response."""


class OpenSkyClient:
    def __init__(
        self,
        settings: Settings,
        session: requests.Session | None = None,
        *,
        max_retries: int = 3,
        backoff: float = 1.0,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.backoff = backoff
        self.timeout = timeout
        self._sleep = sleep
        self._clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0

    def get_states(self, bbox: BoundingBox | None = None) -> StatesSnapshot:
        bbox = bbox or self.settings.bbox
        params = bbox.as_params() if bbox else {}
        payload = self._get_json("/states/all", params)
        try:
            return StatesSnapshot.from_api(payload)
        except ValueError as exc:
            raise OpenSkyError(f"unexpected response shape: {exc}") from exc

    def _get_json(self, path: str, params: dict) -> dict:
        url = f"{API_URL}{path}"
        refreshed_after_401 = False
        attempt = 0
        while True:
            try:
                response = self.session.get(
                    url, params=params, headers=self._auth_headers(), timeout=self.timeout
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt >= self.max_retries:
                    raise OpenSkyError(f"request failed after {attempt + 1} attempts: {exc}") from exc
                self._wait(attempt, None)
                attempt += 1
                continue

            if response.status_code == 401 and self.settings.has_credentials and not refreshed_after_401:
                # Token may have been revoked early; get a fresh one and retry once.
                log.info("Got 401, refreshing access token")
                self._token = None
                refreshed_after_401 = True
                continue

            if response.status_code in RETRY_STATUSES:
                if attempt >= self.max_retries:
                    raise OpenSkyError(
                        f"HTTP {response.status_code} from {path} after {attempt + 1} attempts"
                    )
                self._wait(attempt, response)
                attempt += 1
                continue

            if not response.ok:
                raise OpenSkyError(f"HTTP {response.status_code} from {path}: {response.text[:200]}")

            try:
                return response.json()
            except ValueError as exc:
                raise OpenSkyError(f"response from {path} is not valid JSON") from exc

    def _wait(self, attempt: int, response: requests.Response | None) -> None:
        delay = self.backoff * 2**attempt
        if response is not None:
            retry_after = response.headers.get("X-Rate-Limit-Retry-After-Seconds")
            if retry_after and retry_after.isdigit():
                delay = float(retry_after)
            log.warning("HTTP %s, retrying in %.1fs", response.status_code, delay)
        else:
            log.warning("Connection problem, retrying in %.1fs", delay)
        self._sleep(delay)

    def _auth_headers(self) -> dict[str, str]:
        if not self.settings.has_credentials:
            return {}
        if self._token is None or self._clock() >= self._token_expires_at:
            self._fetch_token()
        return {"Authorization": f"Bearer {self._token}"}

    def _fetch_token(self) -> None:
        try:
            response = self.session.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.settings.client_id,
                    "client_secret": self.settings.client_secret,
                },
                timeout=self.timeout,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise OpenSkyError(f"could not reach token endpoint: {exc}") from exc
        if not response.ok:
            raise OpenSkyError(f"token request failed with HTTP {response.status_code}")
        try:
            body = response.json()
            self._token = body["access_token"]
            expires_in = float(body.get("expires_in", 1800))
        except (ValueError, KeyError, TypeError) as exc:
            raise OpenSkyError("token response is missing access_token") from exc
        self._token_expires_at = self._clock() + max(expires_in - TOKEN_REFRESH_MARGIN, 0)
