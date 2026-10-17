# Awesome AI Catalogs [![Awesome](https://awesome.re/badge.svg)](https://awesome.re)

> A curated list of publicly available [AI Catalogs](https://agent-card.github.io/ai-catalog/), published as an AI Catalog itself.

An AI Catalog (`application/ai-catalog+json`) is a JSON document that indexes AI artifacts such as MCP servers, A2A agents, agent skills, and other catalogs. This repository's [`ai-catalog.json`](ai-catalog.json) is itself an AI Catalog whose entries are public catalogs. It is published unchanged, along with a browsable site.

- **Website:** <https://agent-card.github.io/awesome-ai-catalogs/>
- **AI Catalog:** <https://agent-card.github.io/awesome-ai-catalogs/ai-catalog.json>

Every listed catalog has been validated with the [`ai-catalog` CLI](https://github.com/Agent-Card/ai-catalog-cli) and must stay valid to remain listed.

## Contents

- [Using this catalog](#using-this-catalog)
- [Catalogs](#catalogs)
- [Contributing](#contributing)
- [Related](#related)

## Using this catalog

Every listed catalog is a nested catalog entry (`application/ai-catalog+json`), so any AI Catalog client can crawl the whole list. For example, with the `ai-catalog` CLI:

```sh
ai-catalog catalog add awesome https://agent-card.github.io/awesome-ai-catalogs/ai-catalog.json
ai-catalog search mcp
```

The site's HTML also advertises the catalog with `<link rel="ai-catalog">` for agent-driven discovery.

## Catalogs

<!-- catalogs:start -->

- [AgentAvow](https://agentavow.com/.well-known/ai-catalog.json) - Signed (did:web, ES256) catalog for the AgentAvow trust MCP server; a reference for Trusted-level conformance.
- [anchor-x402](https://api.anchor-x402.com/.well-known/ai-catalog.json) - x402-paid services for AI agents exposed as an A2A agent, an MCP server, and an OpenAPI description.
- [AWS Skills](https://dawright22.github.io/aws_skills/.well-known/ai-catalog.json) - Community agent skills for AWS services such as API Gateway, Bedrock, CloudFormation, CloudWatch, and Cognito.
- [Azure Git-Ape](https://azure.github.io/git-ape/.well-known/ai-catalog.json) - Agent skills for Azure deployments: cost estimation, preflight validation, drift detection, and integration testing.
- [Clairvoyance](https://clairvoyance.fyi/.well-known/ai-catalog.json) - Software design skills for AI coding agents, inspired by A Philosophy of Software Design.
- [Cloudflare Developer Documentation](https://developers.cloudflare.com/.well-known/ai-catalog.json) - Cloudflare API OpenAPI spec, MCP servers, agent skills index, and llms.txt for the Cloudflare developer platform.
- [Datum](https://www.datum.net/.well-known/ai-catalog.json) - MCP server and OpenAPI description for Datum, connected infrastructure for AI companies.
- [DBFlux](https://dbflux.dev/.well-known/ai-catalog.json) - Documentation, llms.txt, an agent skill, and a docs MCP server for DBFlux, a keyboard-first database client.
- [DeepEval](https://deepeval.com/.well-known/ai-catalog.json) - LLM evaluation framework docs (llms.txt), the Confident AI API catalog, and the Confident AI MCP server.
- [Frontman](https://frontman.sh/.well-known/ai-catalog.json) - Agent skills and a read-only OpenAPI for Frontman, a browser-aware frontend coding agent.
- [iammatthias.com](https://iammatthias.com/.well-known/ai-catalog.json) - Personal site exposing llms.txt, an MCP server, and a GraphQL endpoint for searching and reading its content.
- [Kortix](https://www.kortix.com/.well-known/ai-catalog.json) - MCP server for Kortix, an open-source AI operating system for agents, skills, memory, and connectors.
- [Lumis](https://lumis.sh/.well-known/ai-catalog.json) - Docs MCP server and an agent skill for the Lumis syntax highlighter.
- [Magoo](https://magoo.cc/.well-known/ai-catalog.json) - Read-only MCP access to Magoo, a library of component interaction-design behaviors for design systems (Portuguese).
- [Nostria](https://nostria.app/.well-known/ai-catalog.json) - MCP server and OpenAPI descriptions for the Nostria Nostr client and its backend services.
- [Nylas CLI](https://cli.nylas.com/.well-known/ai-catalog.json) - Hosted Nylas MCP servers (US and EU) for email, calendar, and contacts, plus the Nylas CLI llms.txt and API docs.
- [Percona Community](https://percona.community/.well-known/ai-catalog.json) - Semantic search API, llms.txt, and agent instructions for the Percona open source database community site.
- [rimzzlabs.com](https://rimzzlabs.com/.well-known/ai-catalog.json) - Personal site publishing a public OpenAPI, an API catalog linkset, and guestbook and notes agent skills.
- [SmartBench](https://smartbench.ai/.well-known/ai-catalog.json) - Federated ARD registry for discovering and comparing AI models, skills, MCP servers, and agents.
- [Suganthan Mohanadasan](https://suganthan.com/.well-known/ai-catalog.json) - A2A agent, MCP server, and OpenAPI for searching and reading an AI SEO research blog.
- [The Website Specification](https://specification.website/.well-known/ai-catalog.json) - MCP server, A2A agent, agent skill, and knowledge bundle for querying The Website Specification.
- [tldraw](https://tldraw.dev/.well-known/ai-catalog.json) - tldraw SDK migration skill plus a nested catalog for tldraw.com, including its MCP server for reading boards.
- [Weaviate](https://weaviate.io/.well-known/ai-catalog.json) - Agent-oriented guides, llms.txt, and resources for the Weaviate open source vector database.
- [x.md](https://x.pcstyle.dev/.well-known/ai-catalog.json) - MCP server, REST API, and browse-x agent skill for reading public X (Twitter) content.

<!-- catalogs:end -->

## Contributing

Want your catalog listed? [Open an **Add a catalog** issue](https://github.com/Agent-Card/awesome-ai-catalogs/issues/new?template=add-catalog.yml) with its URL, and a bot validates it and opens the pull request for you. You can also add an entry to [`ai-catalog.json`](ai-catalog.json) and open a pull request yourself. CI lints your entry and validates your live catalog automatically. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Related

- [AI Catalog specification](https://agent-card.github.io/ai-catalog/) ([repository](https://github.com/Agent-Card/ai-catalog))
- [ai-catalog-cli](https://github.com/Agent-Card/ai-catalog-cli) - Rust CLI for validating, searching, and pulling from catalogs.
- [ai-catalog-go](https://github.com/Agent-Card/ai-catalog-go) - Go SDK.
- [ai-catalog-rust](https://github.com/Agent-Card/ai-catalog-rust) - Rust libraries.
- [AI Catalog implementations](https://github.com/Agent-Card/ai-catalog/blob/main/docs/implementations.md) - Libraries, tools, and services that implement the specification.
