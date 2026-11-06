"""The one place network calls happen: timeouts, retries, per-host politeness delay."""

import logging
import time
from urllib.parse import urlsplit

import requests
from tenacity import (
    Retrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from pipeline import config

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class RetryableStatusError(Exception):
    def __init__(self, status: int, body: str, url: str) -> None:
        super().__init__(f"{status} from {url}")
        self.status = status
        self.body = body


class HttpClient:
    def __init__(
        self,
        user_agent: str = config.USER_AGENT,
        timeout: float = config.HTTP_TIMEOUT_SECONDS,
        max_attempts: int = config.HTTP_MAX_ATTEMPTS,
        min_delay_per_host: float = config.HTTP_MIN_DELAY_PER_HOST_SECONDS,
    ) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.min_delay_per_host = min_delay_per_host
        self._last_request_at: dict[str, float] = {}

    def get(self, url: str, **kwargs) -> requests.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        return self.request("POST", url, **kwargs)

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        retrying = Retrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential(multiplier=2, max=30),
            retry=retry_if_exception_type(
                (requests.ConnectionError, requests.Timeout, RetryableStatusError)
            ),
            before_sleep=before_sleep_log(log, logging.WARNING),
            reraise=True,
        )
        for attempt in retrying:
            with attempt:
                return self._send(method, url, **kwargs)
        raise AssertionError("unreachable: tenacity reraises on final failure")

    def _send(self, method: str, url: str, **kwargs) -> requests.Response:
        self._wait_for_host(urlsplit(url).hostname or "")
        kwargs.setdefault("timeout", self.timeout)
        resp = self.session.request(method, url, **kwargs)
        if resp.status_code in RETRYABLE_STATUS:
            raise RetryableStatusError(resp.status_code, resp.text, url)
        resp.raise_for_status()
        return resp

    def _wait_for_host(self, host: str) -> None:
        elapsed = time.monotonic() - self._last_request_at.get(host, 0.0)
        if elapsed < self.min_delay_per_host:
            time.sleep(self.min_delay_per_host - elapsed)
        self._last_request_at[host] = time.monotonic()
