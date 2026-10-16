# Contributing

Thanks for helping grow the list! Adding a catalog takes one file and one pull request.

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
2. Create `catalogs/<slug>.json`, where `<slug>` is a lowercase, hyphenated name such as `acme-tools`:

   ```json
   {
     "displayName": "Acme Tools",
     "description": "MCP servers and agent skills for the Acme developer platform.",
     "url": "https://acme.example/.well-known/ai-catalog.json",
     "tags": ["mcp", "skills", "developer-tools"]
   }
   ```

3. Open a pull request. Don't edit `README.md`; the list there is regenerated automatically after merge.

The **Lint AI Catalogs** check fetches your catalog, validates it with the `ai-catalog` CLI, and posts the results in the job summary. Fix any reported errors and push again.

### Listing fields

| Field | Required | Notes |
|---|---|---|
| `displayName` | yes | Name of the catalog or its publisher. Maximum 80 characters. |
| `description` | yes | One line describing what the catalog offers. Maximum 300 characters. |
| `url` | yes | `https://` URL of the catalog document. |
| `tags` | no | Up to 8 lowercase, kebab-case keywords, such as `mcp`, `a2a`, or `skills`. |
| `identifier` | no | Only if you publish the catalog: a `urn:air:<your-domain>:catalog:<name>` identifier whose domain matches `url`. When omitted, the list assigns `https://agent-card.github.io/awesome-ai-catalogs/catalogs/<slug>`. |
| `publisher` | no | `{ "identifier": "...", "displayName": "..." }` describing the catalog publisher. |
| `type` | no | Always `application/ai-catalog+json`; it can be omitted. |

Each listing becomes a nested catalog entry in the published [`.well-known/ai-catalog.json`](https://agent-card.github.io/awesome-ai-catalogs/.well-known/ai-catalog.json).

## Run the checks locally

You need Python 3.10 or later and the [`ai-catalog` CLI](https://github.com/Agent-Card/ai-catalog-cli/releases) on your `PATH` (or set `AI_CATALOG_BIN`).

```sh
# Validate your catalog directly
ai-catalog validate path/to/ai-catalog.json

# Lint listings and validate one listed catalog
python scripts/catalogs.py check --remote acme-tools

# Lint and validate every listed catalog
python scripts/catalogs.py check

# Build the site into _site/ (also validates the aggregate catalog)
python scripts/catalogs.py build
```

## Maintainers

- PRs that only add or change files in `catalogs/` and pass **Lint AI Catalogs** are ready to review for fit and description quality.
- After merge, **Publish site** deploys GitHub Pages and commits the regenerated README list.
- To bump the CLI version, update `version` and `sha256` defaults in `.github/actions/setup-ai-catalog/action.yml`.
