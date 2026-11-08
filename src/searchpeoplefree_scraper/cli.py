"""Command line entry point: ``searchpeoplefree-scraper URL [URL ...]``."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from typing import List, Optional

from . import __version__
from .client import TOKEN_ENV, ScrapeError, SearchPeopleFreeScraper
from .parser import CSV_FIELDS, Person


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="searchpeoplefree-scraper",
        description="Scrape SearchPeopleFree.com profile pages into JSON or CSV.",
    )
    parser.add_argument("urls", nargs="*", help="Profile URLs to scrape")
    parser.add_argument("-i", "--input", help="Text file with one profile URL per line")
    parser.add_argument("-n", "--name", action="append", default=[], help='Search a name, e.g. "John Smith" (repeatable)')
    parser.add_argument("-s", "--state", default="", help="Two-letter state code for --name searches, e.g. WA")
    parser.add_argument("--pages", type=int, default=1, help="Search result pages per name, about 10 profiles each (default: 1)")
    parser.add_argument("--limit", type=int, default=0, help="Stop after this many profiles (default: no limit)")
    parser.add_argument("-t", "--token", help=f"Scrape.do API token (default: ${TOKEN_ENV})")
    parser.add_argument(
        "-f", "--format", choices=("json", "csv"), default="json", help="Output format (default: json)"
    )
    parser.add_argument("-o", "--output", help="Write to this file instead of stdout")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _read_urls(args: argparse.Namespace) -> List[str]:
    urls = list(args.urls)
    if args.input:
        with open(args.input, encoding="utf-8") as handle:
            urls.extend(line.strip() for line in handle if line.strip() and not line.startswith("#"))
    return urls


def _write(people: List[Person], fmt: str, stream) -> None:
    if fmt == "csv":
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for person in people:
            writer.writerow(person.to_row())
    else:
        json.dump([p.to_dict() for p in people], stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    urls = _read_urls(args)
    if not urls and not args.name:
        print("No URLs given. Pass profile URLs, --input FILE or --name NAME.", file=sys.stderr)
        return 2

    try:
        scraper = SearchPeopleFreeScraper(token=args.token)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    for name in args.name:
        try:
            found = scraper.search(name, args.state, args.pages)
        except (ScrapeError, ValueError) as exc:
            print(f"fail  search {name!r}: {exc}", file=sys.stderr)
            continue
        print(f"found {len(found)} profile(s) for {name!r}", file=sys.stderr)
        urls.extend(u for u in found if u not in urls)
    if args.limit > 0:
        urls = urls[: args.limit]

    people: List[Person] = []
    failures = 0
    for url in urls:
        try:
            people.append(scraper.get_profile(url))
            print(f"ok    {url}", file=sys.stderr)
        except (ScrapeError, ValueError) as exc:
            failures += 1
            print(f"fail  {url}: {exc}", file=sys.stderr)

    if args.output:
        newline = "" if args.format == "csv" else None
        with open(args.output, "w", encoding="utf-8", newline=newline) as handle:
            _write(people, args.format, handle)
        print(f"Saved {len(people)} profile(s) to {args.output}", file=sys.stderr)
    else:
        _write(people, args.format, sys.stdout)

    return 1 if failures and not people else 0


if __name__ == "__main__":
    raise SystemExit(main())
