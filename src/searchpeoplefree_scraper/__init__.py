"""Scrape SearchPeopleFree.com profile pages with Python."""

from .client import ScrapeError, SearchPeopleFreeScraper
from .parser import CSV_FIELDS, Person, decode_cfemail, name_search_url, parse_profile, parse_search_results

__all__ = [
    "CSV_FIELDS",
    "Person",
    "ScrapeError",
    "SearchPeopleFreeScraper",
    "decode_cfemail",
    "name_search_url",
    "parse_profile",
    "parse_search_results",
]

__version__ = "0.1.0"
