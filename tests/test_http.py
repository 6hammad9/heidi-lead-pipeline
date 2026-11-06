import pytest
import requests

from pipeline.utils import http
from pipeline.utils.http import HttpClient, RetryableStatusError


class ScriptedSession:
    """Replaces requests.Session: each call returns or raises the next scripted item."""

    def __init__(self, script: list[object]) -> None:
        self.script = list(script)
        self.calls = 0
        self.headers: dict[str, str] = {}

    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        self.calls += 1
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def response(status: int, body: str = "") -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp._content = body.encode()
    return resp


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> HttpClient:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)  # tenacity backoff and politeness
    return HttpClient(max_attempts=3, min_delay_per_host=0)


def test_default_retries_timeouts_then_succeeds(client: HttpClient) -> None:
    client.session = ScriptedSession([requests.exceptions.ReadTimeout(), response(200, "ok")])
    assert client.get("https://example.de").text == "ok"
    assert client.session.calls == 2


def test_narrowed_retry_on_does_not_retry_read_timeout(client: HttpClient) -> None:
    client.session = ScriptedSession([requests.exceptions.ReadTimeout(), response(200)])
    with pytest.raises(requests.exceptions.ReadTimeout):
        client.post("https://api.example.com", retry_on=(RetryableStatusError,))
    assert client.session.calls == 1


def test_narrowed_retry_on_still_retries_error_status(client: HttpClient) -> None:
    client.session = ScriptedSession([response(503, "busy"), response(200, "ok")])
    resp = client.post("https://api.example.com", retry_on=(RetryableStatusError,))
    assert resp.text == "ok"
    assert client.session.calls == 2


def test_retryable_status_carries_status_and_body_after_final_attempt(client: HttpClient) -> None:
    client.session = ScriptedSession([response(503, "busy")] * 3)
    with pytest.raises(RetryableStatusError) as excinfo:
        client.get("https://example.de")
    assert (excinfo.value.status, excinfo.value.body) == (503, "busy")
    assert client.session.calls == 3


def test_client_error_is_not_retried(client: HttpClient) -> None:
    client.session = ScriptedSession([response(404, "missing"), response(200)])
    with pytest.raises(requests.HTTPError):
        client.get("https://example.de/x")
    assert client.session.calls == 1


def test_default_retry_on_covers_network_errors() -> None:
    assert requests.ConnectionError in http.DEFAULT_RETRY_ON
    assert requests.Timeout in http.DEFAULT_RETRY_ON
