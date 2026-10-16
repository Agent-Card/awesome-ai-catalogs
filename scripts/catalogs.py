#!/usr/bin/env python3
"""Lint, build, and publish the Awesome AI Catalogs list.

Every listed catalog lives in ``catalogs/<slug>.json``. This script:

* ``check``  - lints the listing files and (optionally) fetches each remote
               catalog and validates it with the ``ai-catalog`` CLI.
* ``build``  - produces the GitHub Pages site, including the aggregate
               AI Catalog served at ``/.well-known/ai-catalog.json``.
* ``readme`` - regenerates the catalog list in README.md.

Only the Python standard library is used. The ``ai-catalog`` CLI
(https://github.com/Agent-Card/ai-catalog-cli) must be on PATH (or set
``AI_CATALOG_BIN``) for remote validation and for building the site.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOGS_DIR = ROOT / "catalogs"
SITE_SRC = ROOT / "site"
README = ROOT / "README.md"

SITE_URL = os.environ.get("SITE_URL", "https://agent-card.github.io/awesome-ai-catalogs").rstrip("/")
REPO_URL = "https://github.com/Agent-Card/awesome-ai-catalogs"
# Identifiers assigned by this list are non-urn:air URIs under our control,
# as required by the spec's Catalog Projection rules for non-publishers.
ID_BASE = "https://agent-card.github.io/awesome-ai-catalogs/catalogs/"

CATALOG_TYPE = "application/ai-catalog+json"
USER_AGENT = "awesome-ai-catalogs-linter (+https://github.com/Agent-Card/awesome-ai-catalogs)"
MAX_BYTES = 5 * 1024 * 1024
TIMEOUT = 30

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
TAG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")
URN_AIR_RE = re.compile(r"^urn:air:([a-z0-9.-]+):([a-z0-9-]+(?::[a-z0-9-]+)*):([A-Za-z0-9._~-]+)$")

ALLOWED_KEYS = {"identifier", "type", "displayName", "description", "url", "tags", "publisher"}
REQUIRED_KEYS = {"displayName", "description", "url"}
MAX_NAME = 80
MAX_DESCRIPTION = 300
MAX_TAGS = 8

README_START = "<!-- catalogs:start -->"
README_END = "<!-- catalogs:end -->"


def gh_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


@dataclass
class Listing:
    slug: str
    path: Path
    data: dict
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    remote: dict | None = None

    @property
    def identifier(self) -> str:
        return self.data.get("identifier") or ID_BASE + self.slug

    @property
    def sort_key(self) -> str:
        return str(self.data.get("displayName", self.slug)).lower()

    def entry(self) -> dict:
        """Return the Catalog Entry for the aggregate catalog."""
        entry = {
            "identifier": self.identifier,
            "displayName": self.data["displayName"],
            "type": CATALOG_TYPE,
            "description": self.data["description"],
            "url": self.data["url"],
        }
        if self.data.get("tags"):
            entry["tags"] = list(self.data["tags"])
        if self.data.get("publisher"):
            entry["publisher"] = self.data["publisher"]
        return entry


# --------------------------------------------------------------------------
# Loading and linting
# --------------------------------------------------------------------------


def load_listings() -> list[Listing]:
    listings = []
    for path in sorted(CATALOGS_DIR.iterdir()):
        if path.name.startswith(".") or path.is_dir():
            continue
        listing = Listing(slug=path.stem, path=path, data={})
        listings.append(listing)
        if path.suffix != ".json":
            listing.errors.append("listing files must use the .json extension")
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            listing.errors.append(f"not valid UTF-8 JSON: {exc}")
            continue
        if isinstance(data, dict):
            listing.data = data
        else:
            listing.errors.append("listing must be a JSON object")
    return listings


def host_matches(publisher: str, host: str) -> bool:
    return host == publisher or host.endswith("." + publisher)


def lint_listing(listing: Listing) -> None:
    data, err = listing.data, listing.errors.append
    if listing.errors:
        return

    if not SLUG_RE.match(listing.slug):
        err("file name must be a lowercase slug (a-z, 0-9, '-') followed by .json")

    unknown = set(data) - ALLOWED_KEYS
    if unknown:
        err(f"unknown member(s): {', '.join(sorted(unknown))} (allowed: {', '.join(sorted(ALLOWED_KEYS))})")
    missing = REQUIRED_KEYS - set(data)
    if missing:
        err(f"missing required member(s): {', '.join(sorted(missing))}")

    for key, limit in (("displayName", MAX_NAME), ("description", MAX_DESCRIPTION)):
        if key not in data:
            continue
        value = data[key]
        if not isinstance(value, str) or not value.strip():
            err(f"{key} must be a non-empty string")
        elif value != value.strip() or "\n" in value:
            err(f"{key} must be a single line without leading/trailing whitespace")
        elif len(value) > limit:
            err(f"{key} must be at most {limit} characters (got {len(value)})")

    host = ""
    if "url" in data:
        url = data["url"]
        parsed = urllib.parse.urlsplit(url) if isinstance(url, str) else None
        if not parsed or parsed.scheme != "https" or not parsed.hostname:
            err("url must be an absolute https:// URL")
        elif parsed.username or parsed.password or parsed.fragment:
            err("url must not contain credentials or a fragment")
        else:
            host = parsed.hostname.lower()

    if "type" in data and data["type"] != CATALOG_TYPE:
        err(f"type must be {CATALOG_TYPE!r} (or omitted)")

    if "identifier" in data:
        ident = data["identifier"]
        if not isinstance(ident, str) or not ident:
            err("identifier must be a non-empty string")
        elif ident.startswith("urn:air:"):
            match = URN_AIR_RE.match(ident)
            if not match:
                err("identifier must follow urn:air:{publisher}:{namespace}:{name}")
            elif host and not host_matches(match.group(1), host):
                err(
                    f"urn:air publisher '{match.group(1)}' must be the catalog's own domain ('{host}'); "
                    "omit identifier if you are not the publisher"
                )
        elif ident != ID_BASE + listing.slug:
            err(f"identifier must be a urn:air identifier you own, or omitted (defaults to {ID_BASE}{listing.slug})")

    if "tags" in data:
        tags = data["tags"]
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            err("tags must be an array of strings")
        else:
            if len(tags) > MAX_TAGS:
                err(f"at most {MAX_TAGS} tags are allowed")
            bad = [t for t in tags if not TAG_RE.match(t)]
            if bad:
                err(f"tags must be lowercase kebab-case: {', '.join(bad)}")
            if len(set(tags)) != len(tags):
                err("tags must be unique")

    if "publisher" in data:
        pub = data["publisher"]
        if (
            not isinstance(pub, dict)
            or not isinstance(pub.get("identifier"), str)
            or not isinstance(pub.get("displayName"), str)
        ):
            err("publisher must be an object with string identifier and displayName")
        elif set(pub) - {"identifier", "displayName"}:
            err("publisher may only contain identifier and displayName")


def lint_all(listings: list[Listing]) -> None:
    for listing in listings:
        lint_listing(listing)
    seen_urls: dict[str, str] = {}
    seen_ids: dict[str, str] = {}
    for listing in listings:
        if listing.errors:
            continue
        url = listing.data["url"].rstrip("/").lower()
        ident = listing.identifier
        if url in seen_urls:
            listing.errors.append(f"url is already listed in catalogs/{seen_urls[url]}.json")
        if ident in seen_ids:
            listing.errors.append(f"identifier is already used by catalogs/{seen_ids[ident]}.json")
        seen_urls.setdefault(url, listing.slug)
        seen_ids.setdefault(ident, listing.slug)


# --------------------------------------------------------------------------
# Remote validation
# --------------------------------------------------------------------------


def find_cli() -> str | None:
    return os.environ.get("AI_CATALOG_BIN") or shutil.which("ai-catalog")


def require_cli() -> str:
    cli = find_cli()
    if not cli:
        raise SystemExit(
            "The ai-catalog CLI was not found. Install it from "
            "https://github.com/Agent-Card/ai-catalog-cli/releases or set AI_CATALOG_BIN."
        )
    return cli


def run_validator(cli: str, path: Path) -> dict:
    proc = subprocess.run(
        [cli, "validate", "--json", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        message = (proc.stderr or proc.stdout).strip() or f"ai-catalog exited with code {proc.returncode}"
        return {"valid": False, "errors": [{"path": "", "message": message}], "warnings": []}


def fetch(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": f"{CATALOG_TYPE}, application/json;q=0.9"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError(f"response is larger than {MAX_BYTES // (1024 * 1024)} MB")
        return body, response.headers.get("Content-Type", "")


def validate_remote(listing: Listing, cli: str) -> None:
    url = listing.data["url"]
    result: dict = {"reachable": False, "valid": False}
    listing.remote = result
    try:
        body, content_type = fetch(url)
    except urllib.error.HTTPError as exc:
        listing.errors.append(f"fetching {url} failed: HTTP {exc.code}")
        return
    except Exception as exc:  # noqa: BLE001 - surface any network failure to the contributor
        listing.errors.append(f"fetching {url} failed: {exc}")
        return
    result["reachable"] = True

    media_type = content_type.split(";")[0].strip().lower()
    if media_type and media_type != "application/json" and not media_type.endswith("+json"):
        listing.warnings.append(f"served as '{media_type}'; '{CATALOG_TYPE}' or 'application/json' is expected")

    try:
        document = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        listing.errors.append(f"{url} did not return JSON: {exc}")
        return

    fd, name = tempfile.mkstemp(suffix=".json")
    temp_path = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
        report = run_validator(cli, temp_path)
    finally:
        temp_path.unlink(missing_ok=True)

    result["valid"] = bool(report.get("valid"))
    result["conformanceLevel"] = report.get("conformanceLevel")
    for item in report.get("errors", []):
        listing.errors.append(f"ai-catalog validate: {item.get('path') or '$'}: {item.get('message')}")
    for item in report.get("warnings", []):
        message = item.get("message") if isinstance(item, dict) else str(item)
        listing.warnings.append(f"ai-catalog validate: {message}")

    entries = document.get("entries") if isinstance(document, dict) else None
    if isinstance(entries, list):
        result["entryCount"] = len(entries)
        result["types"] = sorted({e["type"] for e in entries if isinstance(e, dict) and isinstance(e.get("type"), str)})
        if not entries:
            listing.errors.append("catalog has no entries; only non-empty catalogs can be listed")


def changed_listing_slugs(base: str) -> set[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base}...HEAD", "--", "catalogs/"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return {Path(line).stem for line in proc.stdout.splitlines() if line.strip()}


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def report(listings: list[Listing], remote_slugs: set[str]) -> bool:
    ok = True
    rows = [
        "## AI Catalog lint results",
        "",
        "| Catalog | Remote validation | Conformance | Entries | Result |",
        "|---|---|---|---|---|",
    ]
    for listing in listings:
        rel = listing.path.relative_to(ROOT).as_posix()
        for message in listing.errors:
            ok = False
            print(f"::error file={rel}::{message}" if gh_actions() else f"ERROR   {rel}: {message}")
        for message in listing.warnings:
            print(f"::warning file={rel}::{message}" if gh_actions() else f"WARNING {rel}: {message}")
        if listing.slug not in remote_slugs and not listing.errors:
            continue
        remote = listing.remote or {}
        result = "❌ " + "<br>".join(md_cell(e) for e in listing.errors) if listing.errors else "✅"
        rows.append(
            f"| {md_cell(str(listing.data.get('displayName', listing.slug)))} (`{rel}`) "
            f"| {'yes' if listing.slug in remote_slugs else 'skipped'} "
            f"| {remote.get('conformanceLevel') or '-'} | {remote.get('entryCount', '-')} | {result} |"
        )
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(rows) + "\n\n")
            handle.write(f"{len(listings)} listing(s) linted, {len(remote_slugs)} remote catalog(s) validated.\n")
    status = "OK" if ok else "FAILED"
    print(f"{len(listings)} listing(s) linted, {len(remote_slugs)} remote catalog(s) validated: {status}")
    return ok


# --------------------------------------------------------------------------
# Site + README generation
# --------------------------------------------------------------------------


def aggregate_catalog(listings: list[Listing]) -> dict:
    return {
        "specVersion": "1.0",
        "host": {
            "displayName": "Awesome AI Catalogs",
            "identifier": SITE_URL + "/",
            "documentationUrl": REPO_URL,
        },
        "entries": [listing.entry() for listing in sorted(listings, key=lambda l: l.sort_key)],
    }


def render_cards(listings: list[Listing]) -> str:
    cards = []
    for listing in sorted(listings, key=lambda l: l.sort_key):
        data, remote = listing.data, listing.remote or {}
        host = urllib.parse.urlsplit(data["url"]).hostname or ""
        tags = "".join(f"<li>{html.escape(t)}</li>" for t in data.get("tags", []))
        meta = []
        if remote.get("conformanceLevel"):
            level = html.escape(remote["conformanceLevel"])
            meta.append(f'<span class="level level-{level}" title="Conformance level">{level}</span>')
        if "entryCount" in remote:
            count = remote["entryCount"]
            meta.append(f'<span>{count} entr{"y" if count == 1 else "ies"}</span>')
        types = remote.get("types", [])
        type_list = "".join(f"<li><code>{html.escape(t)}</code></li>" for t in types)
        search = " ".join([data["displayName"], data["description"], host, *data.get("tags", []), *types]).lower()
        cards.append(
            f"""      <article class="card" data-search="{html.escape(search)}">
        <h2><a href="{html.escape(data['url'])}">{html.escape(data['displayName'])}</a></h2>
        <p class="host">{html.escape(host)}</p>
        <p class="description">{html.escape(data['description'])}</p>
        <div class="meta">{''.join(meta)}</div>
        {f'<ul class="types" aria-label="Entry types">{type_list}</ul>' if type_list else ''}
        <ul class="tags" aria-label="Tags">{tags}</ul>
      </article>"""
        )
    return "\n".join(cards)


def build_site(listings: list[Listing], out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SITE_SRC, out, ignore=shutil.ignore_patterns("*.tmpl"))
    text = json.dumps(aggregate_catalog(listings), indent=2, ensure_ascii=False) + "\n"
    (out / ".well-known").mkdir(parents=True, exist_ok=True)
    (out / ".well-known" / "ai-catalog.json").write_text(text, encoding="utf-8", newline="\n")
    (out / "ai-catalog.json").write_text(text, encoding="utf-8", newline="\n")
    # Ensure GitHub Pages never runs Jekyll, which would drop the dot-directory.
    (out / ".nojekyll").write_text("", encoding="utf-8")

    template = (SITE_SRC / "index.html.tmpl").read_text(encoding="utf-8")
    page = (
        template.replace("{{SITE_URL}}", html.escape(SITE_URL))
        .replace("{{REPO_URL}}", html.escape(REPO_URL))
        .replace("{{COUNT}}", str(len(listings)))
        .replace("{{CARDS}}", render_cards(listings))
    )
    (out / "index.html").write_text(page, encoding="utf-8", newline="\n")


def readme_block(listings: list[Listing]) -> str:
    lines = [README_START, ""]
    for listing in sorted(listings, key=lambda l: l.sort_key):
        data = listing.data
        name = data["displayName"].replace("[", "\\[").replace("]", "\\]")
        lines.append(f"- [{name}]({data['url']}) - {data['description']}")
    lines += ["", README_END]
    return "\n".join(lines)


def update_readme(listings: list[Listing], check_only: bool) -> bool:
    current = README.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(README_START) + r".*?" + re.escape(README_END), re.S)
    if not pattern.search(current):
        raise SystemExit(f"README.md is missing the {README_START} / {README_END} markers")
    updated = pattern.sub(lambda _: readme_block(listings), current)
    if updated == current:
        return True
    if check_only:
        return False
    README.write_text(updated, encoding="utf-8", newline="\n")
    return True


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_check(args: argparse.Namespace) -> int:
    listings = load_listings()
    if not listings:
        print("no listings found in catalogs/", file=sys.stderr)
        return 1
    lint_all(listings)

    known = {l.slug for l in listings}
    if args.remote == "all":
        targets = known
    elif args.remote == "none":
        targets = set()
    elif args.remote == "changed":
        if not args.base:
            raise SystemExit("--remote changed requires --base <git-ref>")
        targets = changed_listing_slugs(args.base) & known
    else:
        targets = {s.strip() for s in args.remote.split(",") if s.strip()}
        unknown = targets - known
        if unknown:
            raise SystemExit(f"unknown listing(s): {', '.join(sorted(unknown))}")

    if targets:
        cli = require_cli()
        for listing in listings:
            if listing.slug in targets and not listing.errors:
                print(f"validating {listing.data['url']} ...", flush=True)
                validate_remote(listing, cli)

    return 0 if report(listings, targets) else 1


def cmd_build(args: argparse.Namespace) -> int:
    listings = load_listings()
    lint_all(listings)
    if any(l.errors for l in listings):
        report(listings, set())
        return 1
    cli = require_cli()
    if args.fetch:
        # Remote metadata is best effort here; the strict check runs in CI.
        for listing in listings:
            validate_remote(listing, cli)
            for message in listing.errors:
                print(f"::warning file=catalogs/{listing.slug}.json::{message}" if gh_actions() else f"WARNING {listing.slug}: {message}")
            listing.errors.clear()
            listing.warnings.clear()

    out = Path(args.out).resolve()
    build_site(listings, out)
    result = run_validator(cli, out / ".well-known" / "ai-catalog.json")
    if not result.get("valid"):
        for item in result.get("errors", []):
            print(f"ERROR aggregate catalog: {item.get('path')}: {item.get('message')}")
        return 1
    print(f"built {out} with {len(listings)} catalogs (aggregate conformance: {result.get('conformanceLevel')})")
    return 0


def cmd_readme(args: argparse.Namespace) -> int:
    listings = load_listings()
    lint_all(listings)
    if any(l.errors for l in listings):
        report(listings, set())
        return 1
    if update_readme(listings, args.check):
        print("README.md is up to date" if args.check else "README.md updated")
        return 0
    print("README.md is out of date; run: python scripts/catalogs.py readme")
    return 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="lint listings and validate remote catalogs")
    check.add_argument(
        "--remote",
        default="all",
        help="remote catalogs to fetch and validate: all (default), none, changed, or comma-separated slugs",
    )
    check.add_argument("--base", help="git ref to diff against when using --remote changed")
    check.set_defaults(func=cmd_check)

    build = sub.add_parser("build", help="build the GitHub Pages site")
    build.add_argument("--out", default="_site", help="output directory (default: _site)")
    build.add_argument("--no-fetch", dest="fetch", action="store_false", help="skip fetching remote metadata")
    build.set_defaults(func=cmd_build)

    readme = sub.add_parser("readme", help="regenerate the catalog list in README.md")
    readme.add_argument("--check", action="store_true", help="fail if README.md is out of date instead of writing")
    readme.set_defaults(func=cmd_readme)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
