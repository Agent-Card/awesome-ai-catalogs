#!/usr/bin/env python3
"""Turn catalog-submission issues into pull requests.

* ``process <issue>`` - validates the catalog submitted in an issue and opens or
                        updates the pull request that adds it. The PR branch is
                        always rebuilt from the latest ``main``, so it never has
                        merge conflicts.
* ``refresh``         - re-runs ``process`` for every open submission PR, so they
                        are rebuilt after another submission is merged.
* ``preview``         - runs validation for an issue body read from a file or
                        stdin without touching git or GitHub (for local testing).

``process`` and ``refresh`` need the ``gh`` CLI with ``GH_TOKEN`` and
``GITHUB_REPOSITORY`` set, and run inside a checkout of this repository.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import catalogs as c  # noqa: E402

LABEL = "catalog-submission"
BRANCH_PREFIX = "catalog-submission/issue-"
MARKER = "<!-- catalog-submission-bot -->"
FIELDS = {
    "Catalog URL": "url",
    "Description": "description",
    "Display name": "displayName",
    "Tags": "tags",
    "Identifier": "identifier",
}


@dataclass
class Outcome:
    entry: dict | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    remote: dict = field(default_factory=dict)


# --------------------------------------------------------------------------
# Building the entry
# --------------------------------------------------------------------------


def parse_issue_form(body: str) -> dict[str, str]:
    """Parse the markdown that GitHub renders for an issue form submission."""
    fields: dict[str, str] = {}
    parts = re.split(r"^###[ \t]+(.+?)[ \t]*$", body or "", flags=re.M)
    for label, value in zip(parts[1::2], parts[2::2]):
        key = FIELDS.get(label.strip())
        if key:
            value = value.strip()
            fields[key] = "" if value == "_No response_" else value
    return fields


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")
    return slug[:64].rstrip("-")


def parse_tags(text: str) -> list[str]:
    tags = []
    for raw in re.split(r"[,\n]", text or ""):
        tag = slugify(raw.strip().lstrip("#"))
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def prepare(fields: dict[str, str], cli: str) -> Outcome:
    """Validate a submission and, if valid, add it to ai-catalog.json on disk."""
    outcome = Outcome()
    url = fields.get("url", "").strip().strip("<>")
    if not url:
        outcome.errors.append("The Catalog URL field is required.")
        return outcome
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        outcome.errors.append(f"{url} must be an absolute https:// URL.")
        return outcome

    probe = c.Entry(index=0, data={"url": url})
    c.validate_remote(probe, cli)
    outcome.remote = probe.remote or {}
    outcome.warnings += probe.warnings
    if probe.errors:
        outcome.errors += probe.errors
        return outcome

    name = fields.get("displayName") or outcome.remote.get("hostName") or parsed.hostname
    document = c.load_catalog(c.read_catalog_text())
    identifier = fields.get("identifier")
    if not identifier:
        # Prefer a slug from the name, then from the domain, so similar names don't collide.
        used = {e.get("identifier") for e in document["entries"]}
        candidates = [c.ID_BASE + s for s in (slugify(name), slugify(parsed.hostname.removeprefix("www."))) if s]
        identifier = next((i for i in candidates if i not in used), candidates[0])
    entry: dict = {
        "identifier": identifier,
        "displayName": name.strip(),
        "type": c.CATALOG_TYPE,
        "description": " ".join(fields.get("description", "").split()),
        "url": url,
    }
    if not entry["description"]:
        outcome.errors.append("The Description field is required.")
        return outcome
    tags = parse_tags(fields.get("tags", ""))
    if tags:
        entry["tags"] = tags

    document["entries"].append(entry)
    text = c.format_catalog(document)
    c.CATALOG.write_text(text, encoding="utf-8", newline="\n")

    # main is kept valid, so any lint failure here is caused by the submission.
    result = c.lint_catalog(text, cli)
    outcome.errors += result.errors
    for item in result.entries:
        outcome.errors += item.errors
    outcome.entry = entry
    return outcome


# --------------------------------------------------------------------------
# Messages
# --------------------------------------------------------------------------


def md_inline(text: str) -> str:
    return re.sub(r"([\\`*_\[\]<>|@#])", r"\\\1", text)


def entry_table(outcome: Outcome) -> str:
    entry, remote = outcome.entry or {}, outcome.remote
    rows = [
        ("Display name", md_inline(entry.get("displayName", ""))),
        ("Identifier", f"`{entry.get('identifier', '')}`"),
        ("Catalog URL", entry.get("url", "")),
        ("Description", md_inline(entry.get("description", ""))),
        ("Tags", ", ".join(f"`{t}`" for t in entry.get("tags", [])) or "-"),
        ("Conformance", remote.get("conformanceLevel") or "-"),
        ("Entries", str(remote.get("entryCount", "-"))),
        ("Entry types", ", ".join(f"`{t}`" for t in remote.get("types", [])) or "-"),
    ]
    return "| | |\n|---|---|\n" + "\n".join(f"| **{k}** | {v} |" for k, v in rows)


def bullet_list(items: list[str]) -> str:
    return "\n".join(f"- {md_inline(i)}" for i in items)


def failure_comment(outcome: Outcome) -> str:
    parts = [
        MARKER,
        "### ❌ This catalog can't be listed yet",
        "",
        bullet_list(outcome.errors),
    ]
    if outcome.warnings:
        parts += ["", "**Warnings**", "", bullet_list(outcome.warnings)]
    parts += [
        "",
        "Fix the catalog or edit this issue to try again. Validation uses the "
        "[`ai-catalog` CLI](https://github.com/Agent-Card/ai-catalog-cli): run `ai-catalog validate <file>` locally.",
    ]
    return "\n".join(parts)


def success_comment(outcome: Outcome, pr_url: str) -> str:
    parts = [MARKER, f"### ✅ Catalog validated: {pr_url}", "", entry_table(outcome)]
    if outcome.warnings:
        parts += ["", "**Warnings**", "", bullet_list(outcome.warnings)]
    parts += ["", "A maintainer will review the pull request. Edit this issue to change the submission."]
    return "\n".join(parts)


def pr_body(outcome: Outcome, issue: dict) -> str:
    parts = [
        f"Adds a catalog submitted in #{issue['number']} by @{issue['author']['login']}.",
        "",
        entry_table(outcome),
        "",
        "The catalog was fetched and validated with the `ai-catalog` CLI, and `ai-catalog.json` passes lint "
        "with the new entry. This branch is rebuilt from `main` whenever `main` or the issue changes.",
    ]
    if outcome.warnings:
        parts += ["", "**Warnings**", "", bullet_list(outcome.warnings)]
    parts += ["", f"Closes #{issue['number']}"]
    return "\n".join(parts)


# --------------------------------------------------------------------------
# GitHub plumbing
# --------------------------------------------------------------------------


def run(*args: str) -> str:
    proc = subprocess.run(list(args), cwd=c.ROOT, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:3])} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def repo() -> str:
    name = os.environ.get("GITHUB_REPOSITORY")
    if not name:
        raise SystemExit("GITHUB_REPOSITORY must be set")
    return name


def open_pr(branch: str) -> dict | None:
    prs = json.loads(run("gh", "pr", "list", "--repo", repo(), "--head", branch, "--state", "open", "--json", "number,url"))
    return prs[0] if prs else None


def bot_login() -> str:
    try:
        return run("gh", "api", "user", "--jq", ".login").strip()
    except RuntimeError:
        return "github-actions[bot]"  # GITHUB_TOKEN can't read /user


def upsert_comment(number: int, body: str) -> None:
    login = bot_login()
    comments = json.loads(run("gh", "api", f"repos/{repo()}/issues/{number}/comments", "--paginate", "--slurp"))
    for comment in (c for page in comments for c in page):
        if MARKER in (comment.get("body") or "") and comment.get("user", {}).get("login") == login:
            run("gh", "api", "-X", "PATCH", f"repos/{repo()}/issues/comments/{comment['id']}", "-f", f"body={body}")
            return
    run("gh", "api", f"repos/{repo()}/issues/{number}/comments", "-f", f"body={body}")


def close_pr(pr: dict, reason: str) -> None:
    run("gh", "pr", "close", str(pr["number"]), "--repo", repo(), "--comment", reason, "--delete-branch")


def process(number: int, cli: str) -> None:
    issue = json.loads(
        run("gh", "issue", "view", str(number), "--repo", repo(), "--json", "number,title,body,state,labels,author")
    )
    branch = f"{BRANCH_PREFIX}{number}"
    pr = open_pr(branch)
    labels = {label["name"] for label in issue["labels"]}
    if issue["state"] != "OPEN" or LABEL not in labels:
        if pr:
            close_pr(pr, f"Closing because #{number} is no longer an open catalog submission.")
        print(f"#{number}: not an open submission; nothing to do")
        return

    run("git", "fetch", "--quiet", "origin", "main")
    run("git", "checkout", "--quiet", "-B", branch, "origin/main")
    outcome = prepare(parse_issue_form(issue["body"]), cli)

    if outcome.errors:
        run("git", "checkout", "--quiet", "--", c.CATALOG_REL)
        upsert_comment(number, failure_comment(outcome))
        if pr:
            close_pr(pr, f"Closing because the submission in #{number} no longer validates. See the issue for details.")
        print(f"#{number}: validation failed ({len(outcome.errors)} error(s))")
        return

    entry = outcome.entry
    title = f"Add {entry['displayName']} to the catalog list"
    run("git", "add", c.CATALOG_REL)
    run("git", "commit", "--quiet", "-m", f"{title}\n\nCloses #{number}")
    run("git", "push", "--quiet", "--force", "origin", f"HEAD:refs/heads/{branch}")
    body = pr_body(outcome, issue)
    if pr:
        run("gh", "pr", "edit", str(pr["number"]), "--repo", repo(), "--title", title, "--body", body)
        url = pr["url"]
    else:
        url = run(
            "gh", "pr", "create", "--repo", repo(), "--base", "main", "--head", branch, "--title", title, "--body", body
        ).strip()
    upsert_comment(number, success_comment(outcome, url))
    print(f"#{number}: {url}")


def refresh(cli: str) -> int:
    prs = json.loads(
        run("gh", "pr", "list", "--repo", repo(), "--state", "open", "--limit", "200", "--json", "headRefName")
    )
    failed = 0
    for pr in prs:
        head = pr["headRefName"]
        if head.startswith(BRANCH_PREFIX) and head[len(BRANCH_PREFIX):].isdigit():
            try:
                process(int(head[len(BRANCH_PREFIX):]), cli)
            except Exception as exc:  # noqa: BLE001 - keep refreshing the other submissions
                failed += 1
                print(f"::error::{head}: {exc}")
    return 1 if failed else 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    proc = sub.add_parser("process", help="validate an issue's submission and open or update its PR")
    proc.add_argument("issue", type=int)
    sub.add_parser("refresh", help="rebuild every open submission PR from main")
    preview = sub.add_parser("preview", help="validate an issue body locally without git or GitHub")
    preview.add_argument("body_file", nargs="?", default="-", help="file containing the issue body (default: stdin)")
    args = parser.parse_args()

    for name in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        os.environ.setdefault(name, "github-actions[bot]")
    for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        os.environ.setdefault(name, "41898282+github-actions[bot]@users.noreply.github.com")

    cli = c.find_cli()
    if args.command == "process":
        process(args.issue, cli)
        return 0
    if args.command == "refresh":
        return refresh(cli)

    body = sys.stdin.read() if args.body_file == "-" else open(args.body_file, encoding="utf-8").read()
    original = c.read_catalog_text()
    try:
        outcome = prepare(parse_issue_form(body), cli)
    finally:
        c.CATALOG.write_text(original, encoding="utf-8", newline="\n")
    print(failure_comment(outcome) if outcome.errors else success_comment(outcome, "(preview)"))
    return 1 if outcome.errors else 0


if __name__ == "__main__":
    sys.exit(main())
