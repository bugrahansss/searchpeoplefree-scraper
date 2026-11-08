"""Fetch SearchPeopleFree pages through the Scrape.do API.

SearchPeopleFree stacks three defenses a plain HTTP client cannot pass:

* It is geofenced to the United States. Requests from other countries are cut
  off before the page loads.
* Cloudflare checks TLS fingerprints and serves JavaScript challenges.
* DataDome sits behind Cloudflare and scores every request on fingerprints
  and behaviour, so passing one layer is not enough.

Sending the request through Scrape.do with ``geoCode=us`` and ``super=true``
routes it through a US residential IP, which clears all three.
"""

from __future__ import annotations

import os
import time
from typing import Iterator, List, Optional

import requests

from .parser import Person, name_search_url, parse_profile, parse_search_results

API_URL = "https://api.scrape.do/"
TOKEN_ENV = "SCRAPEDO_TOKEN"


class ScrapeError(RuntimeError):
    """Raised when a page cannot be fetched."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class SearchPeopleFreeScraper:
    """Fetch and parse SearchPeopleFree profile pages.

    >>> scraper = SearchPeopleFreeScraper(token="YOUR_SCRAPEDO_TOKEN")
    >>> person = scraper.get_profile("https://www.searchpeoplefree.com/find/<name>/<id>")
    >>> person.name, person.phone
    """

    def __init__(
        self,
        token: Optional[str] = None,
        timeout: float = 90.0,
        retries: int = 2,
        session: Optional[requests.Session] = None,
    ):
        self.token = token or os.environ.get(TOKEN_ENV, "")
        if not self.token:
            raise ValueError(
                f"A Scrape.do API token is required. Pass token=... or set {TOKEN_ENV}."
            )
        self.timeout = timeout
        self.retries = max(0, retries)
        self.session = session or requests.Session()

    def fetch(self, url: str) -> str:
        """Return the raw HTML of ``url``, fetched from a US residential IP."""
        params = {"token": self.token, "url": url, "super": "true", "geoCode": "us"}
        last_error: Optional[ScrapeError] = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.get(API_URL, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = ScrapeError(f"Request failed: {exc}")
            else:
                if response.status_code == 200:
                    return response.text
                last_error = ScrapeError(
                    f"Request for {url} failed with status {response.status_code}",
                    status_code=response.status_code,
                )
                # Client errors (bad token, bad URL, not found) will not fix themselves
                if 400 <= response.status_code < 500 and response.status_code != 429:
                    break
            if attempt < self.retries:
                time.sleep(2 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def get_profile(self, url: str) -> Person:
        """Fetch one profile page and parse it."""
        return parse_profile(self.fetch(url), url=url)

    def search(self, name: str, state: str = "", pages: int = 1) -> List[str]:
        """Profile URLs from a name search, about 10 per page.

        ``state`` is an optional two-letter code (``"WA"``). Stops early when a page
        has no results or only repeats earlier ones.
        """
        urls: List[str] = []
        for page in range(1, max(1, pages) + 1):
            found = parse_search_results(self.fetch(name_search_url(name, state, page)))
            fresh = [u for u in found if u not in urls]
            if not fresh:
                break
            urls.extend(fresh)
        return urls

    def search_profiles(self, name: str, state: str = "", pages: int = 1, limit: int = 0) -> Iterator[Person]:
        """Search a name and yield each parsed profile (``limit=0`` means no limit)."""
        urls = self.search(name, state, pages)
        for url in urls[: limit or None]:
            yield self.get_profile(url)
