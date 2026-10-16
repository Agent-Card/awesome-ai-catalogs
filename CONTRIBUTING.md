# Contributing

Thanks for helping grow the list! Adding a catalog is one entry in [`ai-catalog.json`](ai-catalog.json) and one pull request.

## Listing requirements

Your catalog must:

1. Be publicly reachable over `https://` without authentication (ideally at `https://<your-domain>/.well-known/ai-catalog.json`).
2. Pass `ai-catalog validate` from the [ai-catalog CLI](https://github.com/Agent-Card/ai-catalog-cli) with no errors.
3. Contain at least one entry.
4. Be served as JSON, preferably with `Content-Type: application/ai-catalog+json` (`application/json` is accepted).
5. Not already be listed, either directly or as a nested catalog of a listed catalog.

Catalogs that stop meeting these requirements may be removed. A scheduled workflow re-validates every listed catalog weekly.

## Add your catalog

1. Fork this repository.
2. Add a nested catalog entry to `entries` in `ai-catalog.json`, in alphabetical order by `displayName`:

   ```json
   {
     "identifier": "https://agent-card.github.io/awesome-ai-catalogs/catalogs/acme-tools",
     "displayName": "Acme Tools",
     "type": "application/ai-catalog+json",
     "description": "MCP servers and agent skills for the Acme developer platform.",
     "url": "https://acme.example/.well-known/ai-catalog.json",
     "tags": ["mcp", "skills", "developer-tools"]
   }
   ```

3. Run `python scripts/catalogs.py format` (or match the existing two-space formatting by hand).
4. Open a pull request. Don't edit the list in `README.md`; it's regenerated automatically after merge.

The **Lint AI Catalogs** check validates `ai-catalog.json`, then fetches each entry you added or changed and validates it with the `ai-catalog` CLI. Results appear as annotations on the changed lines and in the job summary. Fix any reported errors and push again.

### Entry fields

| Field | Required | Notes |
|---|---|---|
| `identifier` | yes | `https://agent-card.github.io/awesome-ai-catalogs/catalogs/<slug>`, where `<slug>` is lowercase and hyphenated. If you publish the catalog, you may instead use a `urn:air:<your-domain>:catalog:<name>` identifier whose domain matches `url`. |
| `displayName` | yes | Name of the catalog or its publisher. Maximum 80 characters. |
| `type` | yes | Always `application/ai-catalog+json`. |
| `description` | yes | One line describing what the catalog offers. Maximum 300 characters. |
| `url` | yes | `https://` URL of the catalog document. |
| `tags` | no | Up to 8 lowercase, kebab-case keywords, such as `mcp`, `a2a`, or `skills`. |
| `publisher` | no | `{ "identifier": "...", "displayName": "..." }` describing the catalog publisher. |

Identifiers must stay stable once published, so don't change an existing entry's `identifier`.

## Run the checks locally

You need Python 3.10 or later and the [`ai-catalog` CLI](https://github.com/Agent-Card/ai-catalog-cli/releases) on your `PATH` (or set `AI_CATALOG_BIN`).

```sh
# Validate your own catalog directly
ai-catalog validate path/to/ai-catalog.json

# Sort entries and apply canonical formatting
python scripts/catalogs.py format

# Lint ai-catalog.json and validate only your entry (identifier or slug)
python scripts/catalogs.py check --remote acme-tools

# Lint ai-catalog.json and validate every listed catalog
python scripts/catalogs.py check

# Build the site into _site/
python scripts/catalogs.py build
```

## Maintainers

- PRs that only change `ai-catalog.json` and pass **Lint AI Catalogs** are ready to review for fit and description quality.
- After merge, **Publish site** deploys GitHub Pages and commits the regenerated README list.
- To bump the CLI version, update `version` and `sha256` defaults in `.github/actions/setup-ai-catalog/action.yml`.
