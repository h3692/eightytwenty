# eightytwenty

An open-source MCP connector that gives an AI assistant a slide-design methodology for case
competitions, plus search over a curated library of slide "design DNA".

It is AI-agnostic: it targets any client that supports remote MCP connectors. There is no account
and no sign-in.

The library does not contain original decks. Each entry is an abstract layout record (region boxes,
colour and type roles, hierarchy, a short note on why the slide works) and a wireframe drawn from
that record. The source decks never leave the maintainer's machine. Your AI uses a reference as
inspiration and builds the slide with its own tools.

## Status

Early development. Nothing is deployed yet and the tools below don't exist yet.

## Tools (planned)

- `get_playbook` (planned): the methodology. Workflow, slide archetypes, tagline rules, design
  options, a QA checklist, and how to audit the style of a deck you attach in chat.
- `find_references` (planned): search the library by what a slide needs to do, with optional
  filters such as slide type, industry, and data type. Returns short summaries.
- `get_reference` (planned): the full design-DNA record for one result, plus its wireframe.

All tools are read-only. There is no way to upload to or list the whole library.

## What a request sends

- The search text and filters you (or your AI) pass to the tools.
- Your IP address, which is used only for rate limiting.

No account, and queries are not logged.

## License

[MIT](LICENSE)
