// The public connector: four read-only MCP tools at /mcp (stateless Streamable HTTP, default Origin check), the
// Limiter in front of every tool call, and the /docs + /privacy pages. index.ts binds it to the bundled library.
import { DurableObject } from "cloudflare:workers";
import { McpServer } from "@modelcontextprotocol/server";
import { createMcpHandler } from "agents/mcp/server";
import { z } from "zod";
import flow from "../../pipeline/schema/flow.v2.json";
import labels from "../../pipeline/schema/labels.v1.json";
import anatomyAndTaglines from "../../playbook/anatomy-and-taglines.md";
import archetypes from "../../playbook/archetypes.md";
import attachedDecks from "../../playbook/attached-decks.md";
import distinctiveDesign from "../../playbook/distinctive-design.md";
import narrative from "../../playbook/narrative.md";
import qa from "../../playbook/qa.md";
import visualRulesAndDesignOptions from "../../playbook/visual-rules-and-design-options.md";
import workflow from "../../playbook/workflow.md";
import writing from "../../playbook/writing.md";
import docs from "../pages/index.html";
import privacy from "../pages/privacy.html";
import icon from "../pages/icon.svg";
import { DEFAULT_FLAGS, LENGTHS, search, searchFlows, uncached, uncachedFlows, type FlowQuery, type Library, type Query } from "./search";

export { Limiter } from "./limiter";

const PLAYBOOK: Record<string, string> = {
	workflow,
	narrative,
	"anatomy-and-taglines": anatomyAndTaglines,
	archetypes,
	"distinctive-design": distinctiveDesign,
	"visual-rules-and-design-options": visualRulesAndDesignOptions,
	writing,
	qa,
	"attached-decks": attachedDecks,
};
export const STAGES = Object.keys(PLAYBOOK);
const MAX_IMAGE = 30 * 1024;
const MAX_BODY = 4 * 1024 * 1024; // the MCP SDK's default maxRequestBodySize
const enumOf = (values: string[]) => z.enum(values as [string, ...string[]]);
const readOnly = { readOnlyHint: true, destructiveHint: false };
const text = (t: string) => ({ type: "text" as const, text: t });

// Built once per isolate rather than per request (zod schemas are immutable). The McpServer stays per request: the SDK
// refuses to reuse an instance that is serving another request.
const PLAYBOOK_INPUT = z.object({ stage: enumOf(STAGES).optional().describe("Chapter to return; omit for the index and the workflow.") });
const FIND_INPUT = z.object({
	purpose: z.string().min(1).max(1000).describe("What the slide must achieve, in plain words."),
	slide_type: enumOf(labels.properties.archetype.enum).optional().describe("Archetype id (see the archetypes stage of get_playbook)."),
	industry: enumOf(labels.properties.industry.enum).optional(),
	data_type: enumOf(labels.properties.data_type.enum).optional(),
	impact: enumOf(flow.properties.impact.items.enum).optional().describe("Only impact slides of this kind: how reference decks repeat a slide for effect. Use it when the user wants to emphasize or land a key point: shade_ribbon (the previous slide dimmed, a ribbon stating the takeaway), spotlight (one part highlighted), build (revealed step by step), repeat (an earlier slide brought back as a recap). Few exist."),
	k: z.number().int().min(1).max(8).optional().describe("How many results, 1 to 8 (default 8)."),
});
const FLOWS_INPUT = z.object({
	purpose: z.string().min(1).max(1000).describe("What the whole deck must achieve, in plain words."),
	industry: enumOf(labels.properties.industry.enum).optional(),
	length: enumOf(LENGTHS).optional().describe("short: up to 10 slides, medium: 11 to 25, long: more."),
});
const REFERENCE_INPUT = z.object({ id: z.string().regex(/^[A-Za-z0-9-]{1,64}$/, "Use an id exactly as find_references or find_deck_flows returned it.") });
const DECK_ID = /^[0-9a-f]{16}$/; // slide ids are <deck id>-NN
const PLAYBOOK_INDEX = `Playbook stages (call get_playbook with one of these as \`stage\`):\n${STAGES.map((s) => `- \`${s}\`: ${PLAYBOOK[s].match(/^# (.+)$/m)?.[1] ?? s}`).join("\n")}\n\n${workflow}`;

function createServer(env: Env, lib: Library, key: string) {
	// Spends the daily budget only when a search misses the cache, just before the Searcher runs it.
	const spend = async () => {
		const v = await env.LIMITER.get(env.LIMITER.idFromName("global")).spend(key, limitsOf(env));
		if (!v.ok) throw new Error(v.message);
	};

	const server = new McpServer({ name: "eightytwenty", version: "1.0.0" });

	server.registerTool(
		"get_playbook",
		{
			title: "Get the slide-design playbook",
			description: "The 80-20 slide-design methodology for case competition decks. Call it before planning a deck. " +
				"With no stage it returns the index of stages and the workflow; pass a stage for one chapter.",
			inputSchema: PLAYBOOK_INPUT,
			annotations: readOnly,
		},
		async ({ stage }) => {
			return { content: [text(stage ? PLAYBOOK[stage] : PLAYBOOK_INDEX)] };
		},
	);

	server.registerTool(
		"find_references",
		{
			title: "Find reference slides",
			description: "Search the curated library of slide design DNA by what a slide must do. In deck mode, use it after the " +
				"slide-by-slide storyline is confirmed (see the get_playbook workflow). Returns up to k short summaries (id, slide type, " +
				"score, purpose, why it works, the layout's component kinds, impact device if any), at most one per deck; an impact " +
				"filter returns few results. Call get_reference with an id for the full layout. Reference, never copy.",
			inputSchema: FIND_INPUT,
			annotations: readOnly,
		},
		async (args) => {
			const { results, library_version } = await search(env, lib, args, DEFAULT_FLAGS,
				async (q, k) => (await spend(), env.SEARCHER.get(env.SEARCHER.idFromName("global")).search(q, k)));
			if (!results.length)
				return { content: [text(`No references match these filters. Try fewer filters or a broader purpose. (library_version ${library_version})`)] };
			const lines = results.map((r, i) => `${i + 1}. ${r.id} | ${r.slide_type} | score ${r.score}\n   Purpose: ${r.purpose}\n   Why it works: ${r.why_it_works}` +
				`\n   Kinds: ${r.kinds}${r.impact === "none" ? "" : ` | impact: ${r.impact}`}`);
			return { content: [text(`library_version ${library_version}\n\n${lines.join("\n")}\n\nCall get_reference with an id for its layout, mockup and design DNA.`)] };
		},
	);

	server.registerTool(
		"find_deck_flows",
		{
			title: "Find reference deck flows",
			description: "Search the library's deck flows (how strong decks order their sections) by what the whole deck must achieve. " +
				"In deck mode, use it after the slide-by-slide storyline is confirmed (see the get_playbook workflow), before " +
				"find_references. Returns up to 3 summaries (deck id, arc, length, industry, section sequence, " +
				"why the flow works, score). Call get_reference with a deck id for its steps and their slide ids.",
			inputSchema: FLOWS_INPUT,
			annotations: readOnly,
		},
		async (args) => {
			const { results, library_version } = await searchFlows(env, lib, args,
				async (q, k) => (await spend(), env.SEARCHER.get(env.SEARCHER.idFromName("global")).flows(q, k)));
			if (!results.length)
				return { content: [text(`No deck flows match these filters. Try fewer filters or a broader purpose. (library_version ${library_version})`)] };
			const lines = results.map((r, i) => `${i + 1}. ${r.id} | ${r.arc} | ${r.length} deck | ${r.industry} | score ${r.score}\n   Sections: ${r.sections}\n   Why the flow works: ${r.why_the_flow_works}`);
			return { content: [text(`library_version ${library_version}\n\n${lines.join("\n")}\n\nCall get_reference with a deck id for its full flow, then on its steps' slide ids.`)] };
		},
	);

	server.registerTool(
		"get_reference",
		{
			title: "Get a reference slide or deck flow",
			description: "One library slide: its labels (purpose, why it works, archetype, insight device, impact), its component " +
				"layout (v3), its design DNA (the 40 largest region boxes with colour and type roles, text structure) and its mockup " +
				"image. Use an id from find_references. Build your own slide from it; never copy it. " +
				"A deck id from find_deck_flows returns that deck's flow instead: its steps in order, each with a slide id and " +
				"whether that slide is in the library (available).",
			inputSchema: REFERENCE_INPUT,
			annotations: readOnly,
		},
		async ({ id }) => {
			if (DECK_ID.test(id)) {
				const [flow, published] = await env.DB.batch<{ record?: string; id?: string }>([
					env.DB.prepare("SELECT record FROM flows WHERE id = ?").bind(id),
					// published flows may name unpublished slides: those are marked available: false
					env.DB.prepare("SELECT id FROM slides WHERE id IN (SELECT json_extract(value, '$.id') FROM flows, json_each(flows.record, '$.steps') WHERE flows.id = ?)").bind(id),
				]);
				const record = flow.results[0]?.record;
				if (!record) return { content: [text(`No deck flow with id ${id}. Use a deck id returned by find_deck_flows.`)], isError: true };
				const have = new Set(published.results.map((r) => r.id));
				const rec = JSON.parse(record);
				rec.steps = rec.steps.map((s: { id: string }) => ({ ...s, available: have.has(s.id) }));
				return { content: [text(JSON.stringify(rec))] };
			}
			const row = await env.DB.prepare("SELECT dna, impact, layout FROM slides WHERE id = ?").bind(id).first<{ dna: string; impact: string; layout: string }>();
			if (!row) return { content: [text(`No reference with id ${id}. Use an id returned by find_references.`)], isError: true };
			// Busy records are stored with their 40 largest regions only (pipeline/package.py), so no record is too big to return.
			const dna = JSON.stringify({ ...JSON.parse(row.dna), impact: row.impact, layout: JSON.parse(row.layout) });
			const png = await env.ASSETS.fetch(`https://assets.local/wireframes/${id}.png`);
			const bytes = png.ok ? new Uint8Array(await png.arrayBuffer()) : null;
			if (!bytes || bytes.length > MAX_IMAGE) return { content: [text(dna)] };
			let bin = "";
			for (const b of bytes) bin += String.fromCharCode(b);
			return { content: [text(dna), { type: "image" as const, data: btoa(bin), mimeType: "image/png" }] };
		},
	);

	return server;
}

const ANTHROPIC = [["160.79.104.0", 21], ["153.61.208.0", 20]] as const; // Anthropic's published egress ranges
const ip4 = (ip: string) => ip.split(".").reduce((n, octet) => n * 256 + Number(octet), 0);

// Rate-limit key: the shared "anthropic" bucket, an IPv6 /64, or the IPv4 address.
export function clientKey(ip: string | null): string {
	if (!ip) return "unknown";
	if (ip.includes(":")) {
		const [head, tail] = ip.split("::"), h = head ? head.split(":") : [], t = tail ? tail.split(":") : [];
		const groups = tail === undefined ? h : [...h, ...Array(8 - h.length - t.length).fill("0"), ...t];
		return `${groups.slice(0, 4).map((g) => parseInt(g, 16).toString(16)).join(":")}::/64`;
	}
	return ANTHROPIC.some(([net, bits]) => ip4(ip) >>> (32 - bits) === ip4(net) >>> (32 - bits)) ? "anthropic" : ip;
}

const rpcError = (status: number, id: unknown, message: string, headers: Record<string, string> = {}) =>
	Response.json({ jsonrpc: "2.0", id: id ?? null, error: { code: -32000, message } }, { status, headers: { "access-control-allow-origin": "*", ...headers } });

// The body as text, read only up to the SDK's 4 MiB cap: a body without a Content-Length is never buffered beyond it.
const TOO_BIG = Symbol("too big");
async function readCapped(request: Pick<Request, "headers" | "body">): Promise<string | typeof TOO_BIG> {
	if (Number(request.headers.get("content-length") ?? 0) > MAX_BODY) return TOO_BIG;
	const chunks: Uint8Array[] = [];
	let size = 0;
	for await (const chunk of (request.body ?? new ReadableStream()) as ReadableStream<Uint8Array>) {
		if ((size += chunk.byteLength) > MAX_BODY) return TOO_BIG;
		chunks.push(chunk);
	}
	const all = new Uint8Array(size);
	chunks.reduce((at, c) => (all.set(c, at), at + c.byteLength), 0);
	return new TextDecoder().decode(all);
}

const limitsOf = (env: Env) => ({ perMinute: env.LIMIT_PER_MINUTE, perMinuteShared: env.LIMIT_PER_MINUTE_SHARED, dailySearchBudget: env.DAILY_SEARCH_BUDGET });

// Every tools/call counts toward the caller's per-minute limit (uncached searches also spend the daily budget, in createServer).
async function limit(request: Request, env: Env, body: any, key: string): Promise<Response | null> {
	const calls = [body].flat().filter((m) => m?.method === "tools/call");
	if (!calls.length) return null;
	if (Array.isArray(body)) return rpcError(400, null, "Send one tools/call per request (JSON-RPC batches are not supported).");
	const v = await env.LIMITER.get(env.LIMITER.idFromName("global")).check(key, limitsOf(env));
	return v.ok ? null : rpcError(429, body.id, v.message, { "retry-after": String(v.retryAfter) });
}

// Uncached searches (embedding, vector scan, FTS, rerank, MMR, cache write; flow searches too) run here: a Durable Object's CPU time is its
// own, so the Worker stays inside the Free plan's 10 ms per request. The entry exports it bound to the same library.
export const searcher = (lib: Library) => class Searcher extends DurableObject<Env> {
	search(query: Query, key: string) {
		return uncached(this.env, lib, query, DEFAULT_FLAGS, key);
	}
	flows(query: FlowQuery, key: string) {
		return uncachedFlows(this.env, lib, query, key);
	}
};
export type Searcher = InstanceType<ReturnType<typeof searcher>>;

const PAGE_HEADERS = {
	"content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
	"x-content-type-options": "nosniff",
	"referrer-policy": "no-referrer",
};
const PAGES: Record<string, [string, string]> = {
	"/": [docs, "text/html; charset=utf-8"],
	"/docs": [docs, "text/html; charset=utf-8"],
	"/privacy": [privacy, "text/html; charset=utf-8"],
	"/icon.svg": [icon, "image/svg+xml"],
};

export const app = (lib: Library): ExportedHandler<Env> => ({
	async fetch(request, env) {
		const { pathname } = new URL(request.url);
		if (pathname === "/mcp") {
			const raw = request.method === "POST" ? await readCapped(request.clone()) : null;
			if (raw === TOO_BIG) return rpcError(413, null, "The request body is over 4 MiB.");
			const body: any = raw === null ? null : (() => { try { return JSON.parse(raw); } catch { return null; } })();
			const key = clientKey(request.headers.get("cf-connecting-ip"));
			const denied = body ? await limit(request, env, body, key) : null;
			if (denied) return denied;
			// Hand the parsed body to the SDK (its parsedBody option); otherwise it clones and parses the body twice more.
			return createMcpHandler(() => createServer(env, lib, key)).fetch(request, body ? { parsedBody: body } : undefined);
		}
		const page = PAGES[pathname];
		if (page && request.method === "GET") return new Response(page[0], { headers: { "content-type": page[1], ...PAGE_HEADERS } });
		return new Response("Not found", { status: 404 });
	},
});
