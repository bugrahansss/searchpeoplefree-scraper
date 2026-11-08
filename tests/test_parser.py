import csv
import io
import json
import unittest
from pathlib import Path
from unittest import mock

from searchpeoplefree_scraper import (
    CSV_FIELDS, ScrapeError, SearchPeopleFreeScraper, decode_cfemail, name_search_url, parse_profile, parse_search_results,
)
from searchpeoplefree_scraper import cli

SEARCH = (Path(__file__).parent / "fixtures" / "search_jane_doe.html").read_text(encoding="utf-8")
FIXTURE = (Path(__file__).parent / "fixtures" / "profile_jane_doe.html").read_text(encoding="utf-8")
URL = "https://www.searchpeoplefree.com/find/jane-doe/example123"

NO_JSONLD_EMAIL = """
<script type="application/ld+json">{"@type": "Person", "name": "John Roe",
 "address": {"streetAddress": "10 Main St", "addressLocality": "Springfield", "addressRegion": "IL"},
 "telephone": "(217) 555-0100"}</script>
<article class="current-bg">Age 58</article>
<a class="__cf_email__" data-cfemail="5a30352e1a3f223b372a363f7435283d">[email protected]</a>
"""


class DecodeTest(unittest.TestCase):
    def test_decode(self):
        self.assertEqual(decode_cfemail("5a303b343f3e353f1a3f223b372a363f74393537"), "janedoe@example.com")

    def test_bad_input(self):
        self.assertEqual(decode_cfemail("zz"), "")
        self.assertEqual(decode_cfemail(""), "")


class ParseProfileTest(unittest.TestCase):
    def test_full_profile(self):
        p = parse_profile(FIXTURE, url=URL)
        self.assertEqual((p.name, p.age), ("Jane Doe", 41))
        self.assertEqual((p.address, p.city, p.state, p.zip_code), ("2912 Northern Ave", "Washington", "DC", "20001"))
        self.assertEqual(p.phones, ["(202) 555-0147", "(202) 555-0199"])
        self.assertEqual(p.email, "janedoe@example.com")
        self.assertEqual(p.spouse, ["John Doe"])
        self.assertEqual(len(p.relatives), 6)
        self.assertEqual(p.aliases, ["Jane M Doe", "Jane Marie Doe"])
        self.assertEqual(p.past_addresses, ["44 Elm St, Arlington, VA 22201"])
        self.assertEqual(p.url, URL)

    def test_plain_address_and_cf_email_fallback(self):
        p = parse_profile(NO_JSONLD_EMAIL)
        self.assertEqual((p.name, p.age), ("John Roe", 58))
        self.assertEqual((p.address, p.city, p.state, p.zip_code), ("10 Main St", "Springfield", "IL", ""))
        self.assertEqual(p.phones, ["(217) 555-0100"])
        self.assertEqual(p.emails, ["jot@example.org"])
        self.assertEqual((p.spouse, p.relatives), ([], []))

    def test_not_a_profile(self):
        with self.assertRaises(ValueError):
            parse_profile("<html><body>Just a moment...</body></html>")

    def test_csv_row(self):
        row = parse_profile(FIXTURE).to_row()
        self.assertEqual(list(row), CSV_FIELDS)
        self.assertEqual(row["relatives"], "Mary Doe | Robert Smith | Emily Doe | Thomas Doe | Anna Roe | Peter Roe")


class SearchTest(unittest.TestCase):
    def test_search_url(self):
        self.assertEqual(name_search_url("Jane  Doe"), "https://www.searchpeoplefree.com/find/jane-doe")
        self.assertEqual(name_search_url("Jane Doe", "dc", 2), "https://www.searchpeoplefree.com/find/jane-doe/dc/p-2")
        with self.assertRaises(ValueError):
            name_search_url("Jane Doe", "Washington")

    def test_parse_results(self):
        urls = parse_search_results(SEARCH)
        self.assertEqual(len(urls), 3)
        self.assertTrue(all("/find/jane-" in u for u in urls))

    def test_html_fallback(self):
        html = '<a href="/find/jane-doe/abc123XYZ">x</a><a href="/find/jane-doe/dc/p-2">next</a>'
        self.assertEqual(parse_search_results(html), ["https://www.searchpeoplefree.com/find/jane-doe/abc123XYZ"])

    def test_search_stops_on_repeat(self):
        session = mock.Mock()
        session.get.return_value = mock.Mock(status_code=200, text=SEARCH)
        urls = SearchPeopleFreeScraper(token="t", session=session).search("Jane Doe", "DC", pages=3)
        self.assertEqual(len(urls), 3)
        self.assertEqual(session.get.call_count, 2)


class ClientTest(unittest.TestCase):
    def _response(self, status, text=""):
        r = mock.Mock()
        r.status_code, r.text = status, text
        return r

    def test_requires_token(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                SearchPeopleFreeScraper()

    def test_params_and_parse(self):
        session = mock.Mock()
        session.get.return_value = self._response(200, FIXTURE)
        person = SearchPeopleFreeScraper(token="t", session=session).get_profile(URL)
        params = session.get.call_args.kwargs["params"]
        self.assertEqual((params["super"], params["geoCode"], params["url"]), ("true", "us", URL))
        self.assertEqual(person.name, "Jane Doe")

    def test_retries_then_raises(self):
        session = mock.Mock()
        session.get.return_value = self._response(502)
        with mock.patch("time.sleep"):
            with self.assertRaises(ScrapeError) as ctx:
                SearchPeopleFreeScraper(token="t", retries=2, session=session).fetch(URL)
        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(session.get.call_count, 3)

    def test_no_retry_on_401(self):
        session = mock.Mock()
        session.get.return_value = self._response(401)
        with self.assertRaises(ScrapeError):
            SearchPeopleFreeScraper(token="t", session=session).fetch(URL)
        self.assertEqual(session.get.call_count, 1)


class CliTest(unittest.TestCase):
    def _run(self, args):
        session = mock.Mock()
        session.get.return_value = mock.Mock(status_code=200, text=FIXTURE)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("searchpeoplefree_scraper.client.requests.Session", return_value=session), \
                mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = cli.main(args + ["--token", "t"])
        return code, out.getvalue()

    def test_json(self):
        code, out = self._run([URL])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)[0]["age"], 41)

    def test_csv(self):
        code, out = self._run([URL, "-f", "csv"])
        rows = list(csv.DictReader(io.StringIO(out)))
        self.assertEqual(rows[0]["spouse"], "John Doe")

    def test_name_search(self):
        session = mock.Mock()
        session.get.side_effect = [mock.Mock(status_code=200, text=SEARCH)] + [mock.Mock(status_code=200, text=FIXTURE)] * 2
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("searchpeoplefree_scraper.client.requests.Session", return_value=session), \
                mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            code = cli.main(["--name", "Jane Doe", "--limit", "2", "--token", "t"])
        self.assertEqual(code, 0)
        self.assertEqual(len(json.loads(out.getvalue())), 2)

    def test_no_urls(self):
        with mock.patch("sys.stderr", io.StringIO()):
            self.assertEqual(cli.main(["--token", "t"]), 2)


if __name__ == "__main__":
    unittest.main()
