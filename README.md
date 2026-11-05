# eightytwenty

An open-source MCP connector that gives an AI assistant a slide-design methodology for case
competitions, plus search over a curated library of slide "design DNA".

It is AI-agnostic: it targets any client that supports remote MCP connectors. There is no account
and no sign-in.

The library does not contain original decks. Each entry is an abstract layout record (region boxes,
colour and type roles, hierarchy, a short note on why the slide works), a component layout, and a
greyscale wireframe drawn from that layout with placeholder copy. Whole decks are also described as
deck flows: the order of sections and where the deck uses impact slides. The source decks never leave
the maintainer's machine. Your AI uses a reference as inspiration and builds the slide with its own
tools.

## Connect

Add `https://eightytwenty.socratic.workers.dev/mcp` as a remote MCP connector in your client.

## Tools

- `get_playbook`: the methodology. Workflow (storyline first), narrative and impact slides, slide
  archetypes, tagline rules, design options, a QA checklist, and how to audit the style of a deck you
  attach in chat.
- `find_references`: search the library by what a slide needs to do, with optional filters such as
  slide type, industry, data type and impact slide kind. Returns up to 8 short summaries.
- `find_deck_flows`: search whole-deck flows by what the deck needs to do, optionally by industry and
  deck length.
- `get_reference`: the record for one slide result (its 40 largest regions), its layout and wireframe,
  or one deck flow.

All tools are read-only. There is no way to upload to or list the whole library.

## What a request sends

- The search text and filters you (or your AI) pass to the tools.
- Your IP address, which is used only for rate limiting.

No account, and queries are not logged.

## License

[MIT](LICENSE)
