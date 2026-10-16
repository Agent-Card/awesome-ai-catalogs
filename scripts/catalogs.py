#!/usr/bin/env python3
"""Lint, build, and publish the Awesome AI Catalogs list.

The list is ``ai-catalog.json`` at the repository root: an AI Catalog whose
entries are the listed catalogs (``application/ai-catalog+json``). This script:

* ``check``  - validates ``ai-catalog.json`` with the ``ai-catalog`` CLI, applies
               this list's own rules, and fetches and validates listed catalogs.
* ``format`` - rewrites ``ai-catalog.json`` in canonical formatting.
* ``build``  - produces the GitHub Pages site, publishing ``ai-catalog.json``
               unchanged at ``/.well-known/ai-catalog.json``.
* ``readme`` - regenerates the catalog list in README.md.

Only the Python standard library is used. The ``ai-catalog`` CLI
(https://github.com/Agent-Card/ai-catalog-cli) must be on PATH (or set
``AI_CATALOG_BIN``) for ``check`` and ``build``.
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
CATALOG = ROOT / "ai-catalog.json"
CATALOG_REL = "ai-catalog.json"
SITE_SRC = ROOT / "site"
README = ROOT / "README.md"

SITE_URL = "https://agent-card.github.io/awesome-ai-catalogs"
REPO_URL = "https://github.com/Agent-Card/awesome-ai-catalogs"
# Identifiers assigned by this list are non-urn:air URIs under our control,
# as required by the spec's Catalog Projection rules for non-publishers.
ID_BASE = SITE_URL + "/catalogs/"

CATALOG_TYPE = "application/ai-catalog+json"
USER_AGENT = "awesome-ai-catalogs-linter (+https://github.com/Agent-Card/awesome-ai-catalogs)"
MAX_BYTES = 5 * 1024 * 1024
TIMEOUT = 30

SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
TAG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")
URN_AIR_RE = re.compile(r"^urn:air:([a-z0-9.-]+):([a-z0-9-]+(?::[a-z0-9-]+)*):([A-Za-z0-9._~-]+)$")

TOP_LEVEL_KEYS = {"specVersion", "host", "entries"}
ENTRY_KEYS = ["identifier", "displayName", "type", "description", "url", "tags", "publisher"]
REQUIRED_ENTRY_KEYS = {"identifier", "displayName", "type", "description", "url"}
MAX_NAME = 80
MAX_DESCRIPTION = 300
MAX_TAGS = 8

README_START = "<!-- catalogs:start -->"
README_END = "<!-- catalogs:end -->"


def gh_actions() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


@dataclass
class Entry:
    index: int
    data: dict
    line: int | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    remote: dict | None = None

    @property
    def identifier(self) -> str:
        value = self.data.get("identifier")
        return value if isinstance(value, str) else f"entries[{self.index}]"

    @property
    def label(self) -> str:
        name = self.data.get("displayName")
        return f"{name} ({self.identifier})" if isinstance(name, str) else self.identifier

    @property
    def sort_key(self) -> str:
        return str(self.data.get("displayName", "")).casefold()


@dataclass
class Result:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    entries: list[Entry] = field(default_factory=list)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def canonical(document: dict) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def load_catalog(text: str) -> dict:
    document = json.loads(text)
    if not isinstance(document, dict):
        raise ValueError("ai-catalog.json must be a JSON object")
    return document


def identifier_lines(text: str) -> dict[str, int]:
    lines: dict[str, int] = {}
    for number, line in enumerate(text.splitlines(), start=1):
        match = re.match(r'\s*"identifier":\s*"((?:[^"\\]|\\.)*)"', line)
        if match:
            lines.setdefault(json.loads(f'"{match.group(1)}"'), number)
    return lines


def find_cli() -> str:
    cli = os.environ.get("AI_CATALOG_BIN") or shutil.which("ai-catalog")
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


def host_matches(publisher: str, host: str) -> bool:
    return host == publisher or host.endswith("." + publisher)


# --------------------------------------------------------------------------
# List rules (on top of the AI Catalog specification)
# --------------------------------------------------------------------------


def lint_entry(entry: Entry) -> None:
    data, err = entry.data, entry.errors.append
    if not isinstance(data, dict):
        err("entry must be a JSON object")
        return

    unknown = set(data) - set(ENTRY_KEYS)
    if unknown:
        err(f"unknown member(s): {', '.join(sorted(unknown))} (allowed: {', '.join(ENTRY_KEYS)})")
    missing = REQUIRED_ENTRY_KEYS - set(data)
    if missing:
        err(f"missing required member(s): {', '.join(sorted(missing))}")

    if "type" in data and data["type"] != CATALOG_TYPE:
        err(f"type must be {CATALOG_TYPE!r}; this list only contains catalogs")

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
                    f"if you are not the publisher use {ID_BASE}<slug>"
                )
        elif not (ident.startswith(ID_BASE) and SLUG_RE.match(ident[len(ID_BASE):])):
            err(f"identifier must be {ID_BASE}<slug> (lowercase, hyphenated) or a urn:air identifier you own")

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


def lint_catalog(text: str, cli: str) -> Result:
    result = Result()
    try:
        document = load_catalog(text)
    except (json.JSONDecodeError, ValueError) as exc:
        result.errors.append(f"not valid JSON: {exc}")
        return result

    report = run_validator(cli, CATALOG)
    for item in report.get("errors", []):
        result.errors.append(f"ai-catalog validate: {item.get('path') or '$'}: {item.get('message')}")
    for item in report.get("warnings", []):
        result.warnings.append(f"ai-catalog validate: {item.get('message') if isinstance(item, dict) else item}")

    unknown = set(document) - TOP_LEVEL_KEYS
    if unknown:
        result.errors.append(f"unsupported top-level member(s): {', '.join(sorted(unknown))}")
    if text != canonical(document):
        result.errors.append("file is not canonically formatted; run: python scripts/catalogs.py format")

    entries = document.get("entries")
    if not isinstance(entries, list):
        return result
    lines = identifier_lines(text)
    result.entries = [Entry(index=i, data=e) for i, e in enumerate(entries)]
    seen_urls: dict[str, str] = {}
    seen_ids: dict[str, str] = {}
    for entry in result.entries:
        lint_entry(entry)
        entry.line = lines.get(entry.identifier)
        if not isinstance(entry.data, dict):
            continue
        url, ident = entry.data.get("url"), entry.data.get("identifier")
        if isinstance(url, str):
            key = url.rstrip("/").lower()
            if key in seen_urls:
                entry.errors.append(f"url is already listed by {seen_urls[key]}")
            seen_urls.setdefault(key, entry.identifier)
        if isinstance(ident, str):
            if ident in seen_ids:
                entry.errors.append("identifier is already used by another entry")
            seen_ids.setdefault(ident, ident)

    names = [e.sort_key for e in result.entries]
    if names != sorted(names):
        result.errors.append("entries must be sorted alphabetically by displayName (case-insensitive)")
    return result


# --------------------------------------------------------------------------
# Remote validation
# --------------------------------------------------------------------------


def fetch(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": f"{CATALOG_TYPE}, application/json;q=0.9"}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError(f"response is larger than {MAX_BYTES // (1024 * 1024)} MB")
        return body, response.headers.get("Content-Type", "")


def validate_remote(entry: Entry, cli: str) -> None:
    url = entry.data["url"]
    result: dict = {"reachable": False, "valid": False}
    entry.remote = result
    try:
        body, content_type = fetch(url)
    except urllib.error.HTTPError as exc:
        entry.errors.append(f"fetching {url} failed: HTTP {exc.code}")
        return
    except Exception as exc:  # noqa: BLE001 - surface any network failure to the contributor
        entry.errors.append(f"fetching {url} failed: {exc}")
        return
    result["reachable"] = True

    media_type = content_type.split(";")[0].strip().lower()
    if media_type and media_type != "application/json" and not media_type.endswith("+json"):
        entry.warnings.append(f"served as '{media_type}'; '{CATALOG_TYPE}' or 'application/json' is expected")

    try:
        document = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        entry.errors.append(f"{url} did not return JSON: {exc}")
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
        entry.errors.append(f"{url}: ai-catalog validate: {item.get('path') or '$'}: {item.get('message')}")
    for item in report.get("warnings", []):
        message = item.get("message") if isinstance(item, dict) else str(item)
        entry.warnings.append(f"{url}: ai-catalog validate: {message}")

    entries = document.get("entries") if isinstance(document, dict) else None
    if isinstance(entries, list):
        result["entryCount"] = len(entries)
        result["types"] = sorted({e["type"] for e in entries if isinstance(e, dict) and isinstance(e.get("type"), str)})
        if not entries:
            entry.errors.append(f"{url} has no entries; only non-empty catalogs can be listed")


def changed_identifiers(entries: list[Entry], base: str) -> set[str]:
    """Identifiers of entries that are new or differ from the base revision."""
    proc = subprocess.run(
        ["git", "show", f"{base}:{CATALOG_REL}"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8"
    )
    previous: dict[str, dict] = {}
    if proc.returncode == 0:
        try:
            for item in load_catalog(proc.stdout).get("entries") or []:
                if isinstance(item, dict) and isinstance(item.get("identifier"), str):
                    previous[item["identifier"]] = item
        except (json.JSONDecodeError, ValueError):
            pass
    return {e.identifier for e in entries if previous.get(e.identifier) != e.data}


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def annotate(level: str, message: str, line: int | None) -> None:
    if gh_actions():
        location = f"file={CATALOG_REL}" + (f",line={line}" if line else "")
        print(f"::{level} {location}::{message}")
    else:
        print(f"{level.upper():7} {CATALOG_REL}{f':{line}' if line else ''}: {message}")


def report(result: Result, remote_ids: set[str]) -> bool:
    ok = not result.errors
    for message in result.errors:
        annotate("error", message, None)
    for message in result.warnings:
        annotate("warning", message, None)
    rows = []
    for entry in result.entries:
        for message in entry.errors:
            ok = False
            annotate("error", f"{entry.label}: {message}", entry.line)
        for message in entry.warnings:
            annotate("warning", f"{entry.label}: {message}", entry.line)
        if entry.identifier in remote_ids or entry.errors:
            remote = entry.remote or {}
            status = "❌ " + "<br>".join(md_cell(e) for e in entry.errors) if entry.errors else "✅"
            rows.append(
                f"| {md_cell(entry.label)} | {'yes' if entry.identifier in remote_ids else 'skipped'} "
                f"| {remote.get('conformanceLevel') or '-'} | {remote.get('entryCount', '-')} | {status} |"
            )

    summary = f"{len(result.entries)} entries linted, {len(remote_ids)} listed catalog(s) fetched and validated"
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("## AI Catalog lint results\n\n")
            for message in result.errors:
                handle.write(f"- ❌ {message}\n")
            if rows:
                handle.write("\n| Catalog | Fetched | Conformance | Entries | Result |\n|---|---|---|---|---|\n")
                handle.write("\n".join(rows) + "\n")
            handle.write(f"\n{summary}: {'passed' if ok else 'failed'}.\n")
    print(f"{summary}: {'OK' if ok else 'FAILED'}")
    return ok


# --------------------------------------------------------------------------
# Site + README generation
# --------------------------------------------------------------------------


def render_cards(entries: list[Entry]) -> str:
    cards = []
    for entry in entries:
        data, remote = entry.data, entry.remote or {}
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


def build_site(text: str, entries: list[Entry], out: Path) -> None:
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(SITE_SRC, out, ignore=shutil.ignore_patterns("*.tmpl"))
    (out / ".well-known").mkdir(parents=True, exist_ok=True)
    (out / ".well-known" / "ai-catalog.json").write_text(text, encoding="utf-8", newline="\n")
    (out / "ai-catalog.json").write_text(text, encoding="utf-8", newline="\n")
    # Ensure GitHub Pages never runs Jekyll, which would drop the dot-directory.
    (out / ".nojekyll").write_text("", encoding="utf-8")

    template = (SITE_SRC / "index.html.tmpl").read_text(encoding="utf-8")
    page = (
        template.replace("{{SITE_URL}}", html.escape(SITE_URL))
        .replace("{{REPO_URL}}", html.escape(REPO_URL))
        .replace("{{COUNT}}", str(len(entries)))
        .replace("{{CARDS}}", render_cards(entries))
    )
    (out / "index.html").write_text(page, encoding="utf-8", newline="\n")


def readme_block(entries: list[Entry]) -> str:
    lines = [README_START, ""]
    for entry in entries:
        data = entry.data
        name = data["displayName"].replace("[", "\\[").replace("]", "\\]")
        lines.append(f"- [{name}]({data['url']}) - {data['description']}")
    lines += ["", README_END]
    return "\n".join(lines)


def update_readme(entries: list[Entry], check_only: bool) -> bool:
    current = README.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(README_START) + r".*?" + re.escape(README_END), re.S)
    if not pattern.search(current):
        raise SystemExit(f"README.md is missing the {README_START} / {README_END} markers")
    updated = pattern.sub(lambda _: readme_block(entries), current)
    if updated == current:
        return True
    if check_only:
        return False
    README.write_text(updated, encoding="utf-8", newline="\n")
    return True


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def read_catalog_text() -> str:
    return CATALOG.read_text(encoding="utf-8")


def cmd_check(args: argparse.Namespace) -> int:
    cli = find_cli()
    result = lint_catalog(read_catalog_text(), cli)
    known = {e.identifier for e in result.entries}

    if args.remote == "all":
        targets = known
    elif args.remote == "none":
        targets = set()
    elif args.remote == "changed":
        if not args.base:
            raise SystemExit("--remote changed requires --base <git-ref>")
        targets = changed_identifiers(result.entries, args.base)
    else:
        targets = {t.strip() for t in args.remote.split(",") if t.strip()}
        targets = {t if t in known else ID_BASE + t for t in targets}
        unknown = targets - known
        if unknown:
            raise SystemExit(f"unknown identifier(s): {', '.join(sorted(unknown))}")

    for entry in result.entries:
        if entry.identifier in targets and not entry.errors:
            print(f"validating {entry.data['url']} ...", flush=True)
            validate_remote(entry, cli)

    return 0 if report(result, targets) else 1


def cmd_format(args: argparse.Namespace) -> int:
    document = load_catalog(read_catalog_text())
    entries = document.get("entries")
    if isinstance(entries, list) and all(isinstance(e, dict) for e in entries):
        order = {key: i for i, key in enumerate(ENTRY_KEYS)}
        entries.sort(key=lambda e: str(e.get("displayName", "")).casefold())
        document["entries"] = [dict(sorted(e.items(), key=lambda kv: order.get(kv[0], len(order)))) for e in entries]
    CATALOG.write_text(canonical(document), encoding="utf-8", newline="\n")
    print(f"formatted {CATALOG_REL}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    cli = find_cli()
    text = read_catalog_text()
    result = lint_catalog(text, cli)
    if not report(result, set()):
        return 1
    if args.fetch:
        # Remote metadata is best effort here; the strict check runs in CI.
        for entry in result.entries:
            validate_remote(entry, cli)
            for message in entry.errors:
                annotate("warning", f"{entry.label}: {message}", entry.line)
    build_site(text, result.entries, Path(args.out).resolve())
    print(f"built {Path(args.out).resolve()} with {len(result.entries)} catalogs")
    return 0


def cmd_readme(args: argparse.Namespace) -> int:
    document = load_catalog(read_catalog_text())
    entries = [Entry(index=i, data=e) for i, e in enumerate(document.get("entries") or [])]
    if update_readme(entries, args.check):
        print("README.md is up to date" if args.check else "README.md updated")
        return 0
    print("README.md is out of date; run: python scripts/catalogs.py readme")
    return 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="lint ai-catalog.json and validate listed catalogs")
    check.add_argument(
        "--remote",
        default="all",
        help="listed catalogs to fetch and validate: all (default), none, changed, "
        "or comma-separated identifiers or slugs",
    )
    check.add_argument("--base", help="git ref to compare against when using --remote changed")
    check.set_defaults(func=cmd_check)

    fmt = sub.add_parser("format", help="sort entries and rewrite ai-catalog.json in canonical formatting")
    fmt.set_defaults(func=cmd_format)

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
