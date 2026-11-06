"""robots.txt compliance: fetched once per host, cached for the run."""

import logging
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

from pipeline import config
from pipeline.utils.http import HttpClient, RetryableStatusError

log = logging.getLogger(__name__)


class RobotsPolicy:
    def __init__(self, client: HttpClient, user_agent: str = config.USER_AGENT) -> None:
        self.client = client
        self.agent_token = user_agent.split("/")[0]
        self._parsers: dict[str, RobotFileParser | None] = {}  # None = whole host disallowed

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._parsers:
            self._parsers[origin] = self._load(origin)
        parser = self._parsers[origin]
        return parser is not None and parser.can_fetch(self.agent_token, url)

    def _load(self, origin: str) -> RobotFileParser | None:
        parser = RobotFileParser()
        try:
            resp = self.client.get(f"{origin}/robots.txt")
        except requests.HTTPError:
            parser.parse([])  # 4xx: no robots.txt, everything allowed (RFC 9309)
            return parser
        except (RetryableStatusError, requests.RequestException) as e:
            log.warning("robots.txt of %s unavailable (%s): not crawling this host", origin, e)
            return None  # 5xx or unreachable: when in doubt, don't crawl
        parser.parse(resp.text.splitlines())
        return parser
