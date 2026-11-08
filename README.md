# searchpeoplefree-scraper

[![PyPI](https://img.shields.io/pypi/v/searchpeoplefree-scraper)](https://pypi.org/project/searchpeoplefree-scraper/)
[![Python](https://img.shields.io/pypi/pyversions/searchpeoplefree-scraper)](https://pypi.org/project/searchpeoplefree-scraper/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A Python scraper for [SearchPeopleFree.com](https://www.searchpeoplefree.com) person profile pages. One request returns the name, exact age, current and past addresses, every listed phone number and email, aliases, the spouse and relatives, as a Python object, JSON or CSV. Name searches (optionally narrowed to a state) give you the profile URLs.

```bash
pip install searchpeoplefree-scraper
```

## Why a plain request fails

SearchPeopleFree shows more for free than most people search sites, and guards it with more layers than most:

| Defense | What happens |
|---|---|
| **US-only geoblock** | From a non-US IP the connection is cut off before the server answers. Datacenter IPs and most VPNs fail too. |
| **Cloudflare** | TLS fingerprinting, JavaScript challenges and Turnstile. A plain `requests` call gets "Attention Required! \| Cloudflare" (HTTP 403). |
| **DataDome** | A second bot detection layer behind Cloudflare that scores fingerprints and behaviour. Passing Cloudflare alone is not enough. |
| **Email obfuscation** | Emails in the HTML are encoded with Cloudflare's `data-cfemail` XOR cipher and decoded by JavaScript in the browser. |

This package sends each request through the [Scrape.do](https://scrape.do/?utm_source=github&utm_medium=searchpeoplefree-scraper) API with two parameters:

- `geoCode=us` keeps the exit IP in the United States
- `super=true` uses a residential IP and Scrape.do's anti-bot handling for Cloudflare and DataDome

The emails come from the page's JSON-LD block, where they are plain text, so no decoding is needed. A `data-cfemail` decoder is included as a fallback. You need a Scrape.do API token; the free plan includes 1,000 credits a month.

## Quick start

```python
from searchpeoplefree_scraper import SearchPeopleFreeScraper

scraper = SearchPeopleFreeScraper(token="YOUR_SCRAPEDO_TOKEN")  # or set SCRAPEDO_TOKEN
person = scraper.get_profile("https://www.searchpeoplefree.com/find/<name>/<id>")

print(person.name, person.age)
print(person.address, person.city, person.state, person.zip_code)
print(person.phone, person.email)   # first listed phone and email
print(person.phones, person.emails) # all of them
print(person.spouse, person.relatives)
print(person.aliases, person.past_addresses)

# or start from a name search: about 10 profiles per page
for person in scraper.search_profiles("Jane Doe", state="DC", pages=1, limit=5):
    print(person.name, person.age, person.city)
```

`scraper.search(name, state, pages)` returns only the profile URLs; each result page and each profile is one request.

### Command line

```bash
export SCRAPEDO_TOKEN=your_token

# one profile, JSON to stdout
searchpeoplefree-scraper "https://www.searchpeoplefree.com/find/<name>/<id>"

# many profiles, one URL per line, CSV file
searchpeoplefree-scraper --input urls.txt --format csv --output profiles.csv

# search a name in one state, first 5 profiles
searchpeoplefree-scraper --name "Jane Doe" --state DC --limit 5 -f csv -o jane-doe.csv
```

### Output

Run on the fictional test profile in [`tests/fixtures`](tests/fixtures/profile_jane_doe.html):

```json
{
  "name": "Jane Doe",
  "age": 41,
  "address": "2912 Northern Ave",
  "city": "Washington",
  "state": "DC",
  "zip_code": "20001",
  "phones": ["(202) 555-0147", "(202) 555-0199"],
  "emails": ["janedoe@example.com", "jane.m.doe@example.org"],
  "spouse": ["John Doe"],
  "relatives": ["Mary Doe", "Robert Smith", "Emily Doe", "Thomas Doe", "Anna Roe", "Peter Roe"],
  "aliases": ["Jane M Doe", "Jane Marie Doe"],
  "past_addresses": ["44 Elm St, Arlington, VA 22201"],
  "url": "https://www.searchpeoplefree.com/find/jane-doe/example123"
}
```

In CSV output, list fields are joined with ` | `, so every value fits in one cell.

## Fields

| Field | Source on the page |
|---|---|
| `name` | JSON-LD `Person.name` |
| `age` | `article.current-bg` summary text ("Age 41"); it is not in the JSON-LD |
| `address`, `city`, `state`, `zip_code` | JSON-LD `contentLocation.address` (or `address`) |
| `phones` | JSON-LD `telephone` array |
| `emails` | JSON-LD `email` array, falling back to decoding `data-cfemail` links |
| `spouse` | JSON-LD `spouse` (`name` of each person) |
| `relatives` | JSON-LD `relatedTo` (`name` of each person) |
| `aliases` | JSON-LD `additionalName` |
| `past_addresses` | JSON-LD `homeLocation`, minus the current address |

## How the parser works

Every profile page embeds a `<script type="application/ld+json">` block of type `Person` (schema.org). It holds the name, phones, emails, aliases, current and past addresses, spouse and relatives in clean JSON (one test profile listed 37 phones, 30 emails and 54 relatives), and the emails are in plain text there, while the visible HTML hides them behind Cloudflare's email obfuscation. The parser reads that block, then takes the exact age from the profile summary with a regex.

You can also parse HTML you already have, or decode an obfuscated email:

```python
from searchpeoplefree_scraper import decode_cfemail, parse_profile

person = parse_profile(html, url=profile_url)
decode_cfemail("5a303b343f3e353f1a3f223b372a363f74393537")  # 'janedoe@example.com'
```

`parse_profile` raises `ValueError` when the page has no `Person` JSON-LD block, which usually means a challenge page, a search page or a removed profile.

## Limits

- **Name searches only.** Phone, address and email lookups are not wrapped; pass the profile URLs they lead to instead.
- **Credits.** Every page (search or profile) is one request through a US residential IP: 10 Scrape.do credits in our tests.
- **Layout changes.** If SearchPeopleFree changes its markup, `parse_profile` may return empty fields. Open an issue with the field that broke.
- **Errors.** Non-200 responses raise `ScrapeError` with the status code. Server errors and 429s are retried twice; client errors are not.

## Responsible use

This data describes real people. Do not use it to make decisions about employment, housing, credit or insurance: in the US those uses are regulated by the Fair Credit Reporting Act. Honor opt-out requests, follow the privacy laws that apply to you, and follow SearchPeopleFree's terms. This is not legal advice.

## Development

```bash
git clone https://github.com/bugrahansss/searchpeoplefree-scraper
cd searchpeoplefree-scraper
pip install -e .
python -m unittest discover -s tests -v
```

The tests run offline against a fictional fixture page.

## License

MIT

---

Source: [SearchPeopleFree.com Scraping: Extract Emails, Phones, and Family Data](https://scrape.do/blog/search-people-free-scraping/)
