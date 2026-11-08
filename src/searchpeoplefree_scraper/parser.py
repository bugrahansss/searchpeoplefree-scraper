"""Parse a SearchPeopleFree.com person profile page into structured data.

The page carries almost everything in one place: a ``<script type="application/ld+json">``
block of type ``Person`` with the name, every phone and email, the current address
(``contentLocation.address``), the spouse and the relatives (``relatedTo``).

Two things are not in it, or not always:

* **Age.** It is only in the visible profile summary, ``<article class="current-bg">``,
  as "Age 70".
* **Emails in the HTML.** The visible emails are hidden by Cloudflare's email
  obfuscation (``data-cfemail``, a one-byte XOR cipher). JSON-LD has them in plain
  text, so the decoder here is only a fallback for pages without JSON-LD emails.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from bs4 import BeautifulSoup


@dataclass
class Person:
    """One SearchPeopleFree profile."""

    name: str = ""
    age: Optional[int] = None
    address: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    phones: List[str] = field(default_factory=list)
    emails: List[str] = field(default_factory=list)
    spouse: List[str] = field(default_factory=list)
    relatives: List[str] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    past_addresses: List[str] = field(default_factory=list)
    url: str = ""

    @property
    def phone(self) -> str:
        """The first listed phone, usually the primary one."""
        return self.phones[0] if self.phones else ""

    @property
    def email(self) -> str:
        """The first listed email, usually the primary one."""
        return self.emails[0] if self.emails else ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_row(self, separator: str = " | ") -> Dict[str, Any]:
        """A flat dict for CSV output; list fields are joined with ``separator``."""
        row = self.to_dict()
        for key in ("phones", "emails", "spouse", "relatives", "aliases", "past_addresses"):
            row[key] = separator.join(row[key])
        return row


CSV_FIELDS = [
    "name", "age", "address", "city", "state", "zip_code", "phones", "emails",
    "spouse", "relatives", "aliases", "past_addresses", "url",
]

AGE_RE = re.compile(r"\bAge\s+(\d{1,3})\b")
BASE_URL = "https://www.searchpeoplefree.com"
PROFILE_RE = re.compile(r"searchpeoplefree\.com/find/[^/?#]+/[A-Za-z0-9]{6,}$|^/find/[^/?#]+/[A-Za-z0-9]{6,}$")


def _squash(value: Any) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _clean_strings(values: Iterable[Any]) -> List[str]:
    seen, out = set(), []
    for value in values:
        if isinstance(value, dict):
            value = value.get("name")
        if not isinstance(value, str):
            continue
        value = _squash(value)
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def decode_cfemail(encoded: str) -> str:
    """Decode a Cloudflare ``data-cfemail`` string.

    The first byte (two hex digits) is the key; every following byte is XORed with it.
    Returns "" for anything that is not valid hex.
    """
    try:
        data = bytes.fromhex(encoded)
    except (ValueError, TypeError):
        return ""
    if len(data) < 2:
        return ""
    key = data[0]
    try:
        return bytes(b ^ key for b in data[1:]).decode("utf-8")
    except UnicodeDecodeError:
        return ""


def _iter_jsonld(soup: BeautifulSoup) -> Iterable[Dict[str, Any]]:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for item in _as_list(data):
            if not isinstance(item, dict):
                continue
            yield item
            for node in _as_list(item.get("@graph")) + _as_list(item.get("mainEntity")):
                if isinstance(node, dict):
                    yield node


def find_person_jsonld(soup: BeautifulSoup) -> Dict[str, Any]:
    """Return the first JSON-LD object whose ``@type`` is ``Person``, or {}."""
    for item in _iter_jsonld(soup):
        kind = item.get("@type")
        if kind == "Person" or (isinstance(kind, list) and "Person" in kind):
            return item
    return {}


def _address_of(entity: Dict[str, Any]) -> Dict[str, Any]:
    for holder in (entity.get("contentLocation"), entity):
        for place in _as_list(holder):
            if not isinstance(place, dict):
                continue
            address = place.get("address")
            for candidate in _as_list(address):
                if isinstance(candidate, dict):
                    return candidate
    return {}


def format_address(address: Dict[str, Any]) -> str:
    """'12 Main St, Springfield, IL 62701' from a schema.org PostalAddress."""
    street = _squash(address.get("streetAddress"))
    city = _squash(address.get("addressLocality"))
    region = " ".join(x for x in (_squash(address.get("addressRegion")), _squash(address.get("postalCode"))) if x)
    return ", ".join(x for x in (street, city, region) if x)


def parse_search_results(html: str) -> List[str]:
    """Profile URLs on a name search page, in page order.

    Read from the page's ``ItemList`` JSON-LD block, falling back to
    ``/find/<name>/<id>`` links in the HTML.
    """
    soup = BeautifulSoup(html, "html.parser")
    urls: List[str] = []
    for item in _iter_jsonld(soup):
        if item.get("@type") == "ItemList":
            for element in _as_list(item.get("itemListElement")):
                if isinstance(element, dict) and isinstance(element.get("url"), str):
                    urls.append(element["url"])
    if not urls:
        urls = [a["href"] for a in soup.find_all("a", href=True) if PROFILE_RE.search(a["href"])]
    out, seen = [], set()
    for url in urls:
        if url.startswith("/"):
            url = BASE_URL + url
        if PROFILE_RE.search(url) and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def name_search_url(name: str, state: str = "", page: int = 1) -> str:
    """URL of a name search, e.g. ``name_search_url("John Smith", "WA", 2)``."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        raise ValueError("A name is required.")
    url = f"{BASE_URL}/find/{slug}"
    state = state.strip().lower()
    if state:
        if not re.fullmatch(r"[a-z]{2}", state):
            raise ValueError("State must be a two-letter code such as WA.")
        url += f"/{state}"
    if page > 1:
        url += f"/p-{page}"
    return url


def parse_profile(html: str, url: str = "") -> Person:
    """Parse the HTML of one SearchPeopleFree profile page.

    Raises ``ValueError`` when the page has no ``Person`` JSON-LD block, which usually
    means a block page, a search results page or a removed profile was passed in.
    """
    soup = BeautifulSoup(html, "html.parser")
    entity = find_person_jsonld(soup)
    if not entity:
        raise ValueError(
            "No profile data found. Expected a SearchPeopleFree person page with a "
            "Person JSON-LD block (got a block page, search page or removed profile?)."
        )

    person = Person(url=url, name=_squash(entity.get("name")))
    address = _address_of(entity)
    person.address = _squash(address.get("streetAddress"))
    person.city = _squash(address.get("addressLocality"))
    person.state = _squash(address.get("addressRegion"))
    person.zip_code = _squash(address.get("postalCode"))
    person.phones = _clean_strings(_as_list(entity.get("telephone")))
    person.emails = _clean_strings(_as_list(entity.get("email")))
    person.spouse = _clean_strings(_as_list(entity.get("spouse")))
    person.relatives = _clean_strings(_as_list(entity.get("relatedTo")))
    person.aliases = _clean_strings(_as_list(entity.get("additionalName")))
    current = ", ".join(p for p in (person.address, person.city) if p)
    past = []
    for place in _as_list(entity.get("homeLocation")):
        if not isinstance(place, dict) or not isinstance(place.get("address"), dict):
            continue
        line = format_address(place["address"])
        if line and not line.startswith(current or "\0"):
            past.append(line)
    person.past_addresses = _clean_strings(past)

    # Age: only in the visible summary
    summary = soup.find("article", class_="current-bg")
    match = AGE_RE.search(summary.get_text(" ")) if summary is not None else None
    if match:
        person.age = int(match.group(1))

    # Emails: fall back to the Cloudflare-obfuscated links in the HTML
    if not person.emails:
        person.emails = _clean_strings(
            decode_cfemail(tag.get("data-cfemail", "")) for tag in soup.find_all(attrs={"data-cfemail": True})
        )

    return person
