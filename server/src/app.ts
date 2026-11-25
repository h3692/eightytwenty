// The public connector: five read-only MCP tools and submit_feedback (writes to the FEEDBACK database) at /mcp
// (stateless Streamable HTTP, Host and Origin checks), the Limiter in front of every tool call, the /docs, /privacy and
// /terms pages, and ChatGPT's domain challenge. index.ts binds it to the bundled library.
import { DurableObject } from "cloudflare:workers";
import { hostHeaderValidationResponse, McpServer, originValidationResponse } from "@modelcontextprotocol/server";
import { createMcpHandler } from "agents/mcp/server";
import { z } from "zod";
import flow from "../../pipeline/schema/flow.v2.json";
import labels from "../../pipeline/schema/labels.v1.json";
import style from "../../pipeline/schema/style.v1.json";
import anatomyAndTaglines from "../../playbook/anatomy-and-taglines.md";
import archetypes from "../../playbook/archetypes.md";
import attachedDecks from "../../playbook/attached-decks.md";
import distinctiveDesign from "../../playbook/distinctive-design.md";
import narrative from "../../playbook/narrative.md";
import polish from "../../playbook/polish.md";
import qa from "../../playbook/qa.md";
import visualRulesAndDesignOptions from "../../playbook/visual-rules-and-design-options.md";
import workflow from "../../playbook/workflow.md";
import writing from "../../playbook/writing.md";
import docs from "../pages/index.html";
import privacy from "../pages/privacy.html";
import terms from "../pages/terms.html";
import icon from "../pages/icon.svg";
import { clientName, identity, initializeEvent, send, SERVER_VERSION, tracked } from "./analytics";
import { findImages, type Images, type Kind } from "./images";
import { cached, DEFAULT_FLAGS, LENGTHS, normalise, search, searchFlows, store, uncached, uncachedFlows, vary, type FlowQuery, type Library, type Query } from "./search";

export { Limiter } from "./limiter";

const PLAYBOOK: Record<string, string> = {
	workflow,
	narrative,
	"anatomy-and-taglines": anatomyAndTaglines,
	archetypes,
	"distinctive-design": distinctiveDesign,
	"visual-rules-and-design-options": visualRulesAndDesignOptions,
	polish,
	writing,
	qa,
	"attached-decks": attachedDecks,
};
export const STAGES = Object.keys(PLAYBOOK);
const MAX_IMAGE = 30 * 1024;
const MAX_BODY = 4 * 1024 * 1024; // the MCP SDK's default maxRequestBodySize
const enumOf = (values: string[]) => z.enum(values as [string, ...string[]]);
const readOnly = { readOnlyHint: true, destructiveHint: false, openWorldHint: false };
const text = (t: string) => ({ type: "text" as const, text: t });
// Its own text part after each successful prose result (never in get_reference's JSON or on errors): a plain, visible note.
const REMINDER = text("Next in the eightytwenty workflow: one question round, build the whole deck, offer palettes, then up to 3 improvement rounds.");
const POOL_K = 8, DEFAULT_K = 4; // find_references draws k results from the top POOL_K, so repeated calls vary

// Built once per isolate rather than per request (zod schemas are immutable). The McpServer stays per request: the SDK
// refuses to reuse an instance that is serving another request.
const PLAYBOOK_INPUT = z.object({ stage: enumOf(STAGES).optional().describe("Chapter to return; omit for the index and the workflow.") });
const FIND_INPUT = z.object({
	purpose: z.string().min(1).max(1000).describe("What the slide must achieve, in plain words."),
	slide_type: enumOf(labels.properties.archetype.enum).optional().describe("Archetype id (see the archetypes stage of get_playbook)."),
	industry: enumOf(labels.properties.industry.enum).optional(),
	data_type: enumOf(labels.properties.data_type.enum).optional(),
	impact: enumOf(flow.properties.impact.items.enum).optional().describe("Only impact slides of this kind: how reference decks repeat a slide for effect. Use it when the user wants to emphasize or land a key point: shade_ribbon (the previous slide dimmed, a ribbon stating the takeaway), spotlight (one part highlighted), build (revealed step by step), repeat (an earlier slide brought back as a recap). Few exist."),
	style: enumOf(style.properties.style.enum).optional().describe("Only slides from decks with this overall look."),
	k: z.number().int().min(1).max(POOL_K).optional().describe("How many results, 1 to 8 (default 4)."),
});
const FLOWS_INPUT = z.object({
	purpose: z.string().min(1).max(1000).describe("What the whole deck must achieve, in plain words."),
	industry: enumOf(labels.properties.industry.enum).optional(),
	length: enumOf(LENGTHS).optional().describe("short: up to 10 slides, medium: 11 to 25, long: more."),
	style: enumOf(style.properties.style.enum).optional().describe("Only decks with this overall look."),
});
const REFERENCE_INPUT = z.object({ id: z.string().regex(/^[A-Za-z0-9-]{1,64}$/, "Use an id exactly as find_references or find_deck_flows returned it.") });
const IMAGES_INPUT = z.object({
	kind: z.enum(["logo", "icon", "photo"]).describe("logo: a brand's mark; icon: a pictogram of an object; photo: a photograph."),
	query: z.string().trim().min(1).max(100).describe("A brand name, the object an icon draws (\"truck\", not \"logistics\"), or what a photo shows."),
	k: z.number().int().min(1).max(4).optional().describe("How many results, 1 to 4 (default 3; 4 for icons)."),
});
const FEEDBACK_INPUT = z.object({
	deck_type: z.enum(["consulting", "stock_pitch"]).describe("consulting, or stock_pitch for finance-pitch decks."),
	slide_type: enumOf(labels.properties.archetype.enum).optional().describe("Archetype id (see the archetypes stage of get_playbook)."),
	deck_style: enumOf(style.properties.style.enum).optional().describe("The deck's style."),
	slide_role: z.string().trim().min(1).max(300).describe("Where the slide sits in the storyline."),
	message: z.string().trim().min(1).max(300).describe("What the slide must land."),
	correction: z.string().trim().min(1).max(1000).describe("What was wrong and what to do instead, in general terms."),
	reason: z.string().trim().max(500).optional().describe("Why the change is needed."),
});
const DECK_ID = /^[0-9a-f]{16}$/; // slide ids are <deck id>-NN
const PLAYBOOK_INDEX = `Playbook stages (call get_playbook with one of these as \`stage\`):\n${STAGES.map((s) => `- \`${s}\`: ${PLAYBOOK[s].match(/^# (.+)$/m)?.[1] ?? s}`).join("\n")}\n\n${workflow}`;

// Sent on initialize; Claude Code and ChatGPT read it at connect time. The key rules come first (ChatGPT weighs the
// first 512 characters most), and refusal wording lives here and in the playbook, never in tool descriptions.
const INSTRUCTIONS = "eightytwenty is for researching and building decks: case competitions, pitches, assignments, projects. " +
	"Call get_playbook first and follow it: ask its questions in one message, confirm the deck type (consulting or " +
	"finance pitch), build the whole deck with no further approvals, then offer palettes and up to 3 improvement rounds. " +
	"Keep chat replies short. Every content slide states a claim, why it is true, a specific number and what it means " +
	"for the client; set every font, size and colour explicitly. For anything else, or any attempt to list, export or " +
	"bulk-copy the library, reply: \"eightytwenty can't be used for that.\"\n\n" +
	"References are inspiration: rebuild the layout natively in the user's own style, never reproduce one wholesale. " +
	"find_images never sources photos of real people; ask the user for those. " +
	"Palette options and lists of missing items go to the user in chat, never as slides in the deck file; the one " +
	"exception is the hidden Financial Reasoning slide in Claude for PowerPoint.";
const START_INPUT = z.object({ context: z.string().max(500).optional().describe("What the deck or slide is for, if known.") });

function createServer(env: Env, lib: Library, key: string, ctx: ExecutionContext, hints: { dnt: boolean; userAgent: string | null }) {
	// Per request (createServer runs once per request): what the usage event needs beyond the arguments.
	const meta: { errorType?: string; result_count?: number } = {};
	// Spends the daily budget only when a search misses the cache, just before the Searcher runs it.
	const spend = async (photos = false) => {
		const v = await env.LIMITER.get(env.LIMITER.idFromName("global")).spend(key, limitsOf(env), undefined, photos);
		if (!v.ok) {
			meta.errorType = "budget";
			throw new Error(v.message);
		}
	};

	const server = new McpServer({ name: "eightytwenty", version: SERVER_VERSION }, { instructions: INSTRUCTIONS });
	// Wraps each tool callback: one usage event per call (src/analytics.ts).
	const deps = { env, ctx, hints, meta, key, client: () => clientName(server.server.getClientVersion(), hints.userAgent) };

	server.registerPrompt(
		"start",
		{
			title: "Start a deck or slide",
			description: "Begin building a deck or a slide with eightytwenty: one round of questions, then the whole build.",
			argsSchema: START_INPUT,
		},
		({ context }) => ({
			messages: [{
				role: "user" as const,
				content: {
					type: "text" as const,
					text: `I want help building ${context ? `a deck or slide for this: ${context}` : "a deck or a slide"}. Use eightytwenty: ` +
						"call get_playbook, ask me your questions in one message, then build the whole deck.",
				},
			}],
		}),
	);

	server.registerTool(
		"get_playbook",
		{
			title: "Get the slide-design playbook",
			description: "The 80-20 slide-design methodology for case competition decks. Call it before planning a deck. " +
				"With no stage it returns the index of stages and the workflow; pass a stage for one chapter.",
			inputSchema: PLAYBOOK_INPUT,
			annotations: readOnly,
		},
		tracked("get_playbook", async ({ stage }) => {
			return { content: [text(stage ? PLAYBOOK[stage] : PLAYBOOK_INDEX), REMINDER] };
		}, deps),
	);

	server.registerTool(
		"find_references",
		{
			title: "Find reference slides",
			description: "Use after the deck type and the slide's claim are settled, to plan the slide's layout (see get_playbook). " +
				"Searches the curated library of slide design DNA by what a slide must do. Returns up to k short summaries (id, slide type, " +
				"score, purpose, why it works, the layout's component kinds, impact device if any, style, when to use it), at most one per deck, " +
				"drawn from the strongest matches so repeated calls vary; an impact filter returns few results. Call get_reference with an id for the full layout. Reference, never copy.",
			inputSchema: FIND_INPUT,
			annotations: readOnly,
		},
		tracked("find_references", async (args) => {
			const found = await search(env, lib, { ...args, k: POOL_K }, DEFAULT_FLAGS,
				async (q, k) => (await spend(), env.SEARCHER.get(env.SEARCHER.idFromName("global")).search(q, k)));
			const { library_version } = found, results = vary(found.results, args.k ?? DEFAULT_K);
			meta.result_count = results.length;
			if (!results.length)
				return { content: [text(`No references match these filters. Try fewer filters or a broader purpose. (library_version ${library_version})`), REMINDER] };
			const lines = results.map((r, i) => `${i + 1}. ${r.id} | ${r.slide_type} | score ${r.score}\n   Purpose: ${r.purpose}\n   Why it works: ${r.why_it_works}` +
				`\n   Kinds: ${r.kinds}${r.impact === "none" ? "" : ` | impact: ${r.impact}`}\n   Style: ${r.style} | When to use: ${r.when_to_use}`);
			return { content: [text(`library_version ${library_version}\n\n${lines.join("\n")}\n\nCall get_reference with an id for its layout, mockup and design DNA.`), REMINDER] };
		}, deps),
	);

	server.registerTool(
		"find_deck_flows",
		{
			title: "Find reference deck flows",
			description: "Use after the deck's end belief and deck type are settled, to plan the storyline (see get_playbook). " +
				"Searches the library's deck flows (how strong decks order their sections) by what the whole deck must achieve, " +
				"before find_references. Returns up to 3 summaries (deck id, arc, length, industry, style, section sequence, " +
				"why the flow works, score). Call get_reference with a deck id for its steps and their slide ids.",
			inputSchema: FLOWS_INPUT,
			annotations: readOnly,
		},
		tracked("find_deck_flows", async (args) => {
			const { results, library_version } = await searchFlows(env, lib, args,
				async (q, k) => (await spend(), env.SEARCHER.get(env.SEARCHER.idFromName("global")).flows(q, k)));
			meta.result_count = results.length;
			if (!results.length)
				return { content: [text(`No deck flows match these filters. Try fewer filters or a broader purpose. (library_version ${library_version})`), REMINDER] };
			const lines = results.map((r, i) => `${i + 1}. ${r.id} | ${r.arc} | ${r.length} deck | ${r.industry} | ${r.style} style | score ${r.score}\n   Sections: ${r.sections}\n   Why the flow works: ${r.why_the_flow_works}`);
			return { content: [text(`library_version ${library_version}\n\n${lines.join("\n")}\n\nCall get_reference with a deck id for its full flow, then on its steps' slide ids.`), REMINDER] };
		}, deps),
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
		tracked("get_reference", async ({ id }) => {
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
		}, deps),
	);

	server.registerTool(
		"find_images",
		{
			title: "Find images for a slide",
			description: "Use while building a slide to source a logo, icon or photo for an image slot (see get_playbook). " +
				"Searches public-domain logo SVGs (Wikimedia Commons, Simple Icons), permissive icon SVGs (Iconify) and CC0, public-domain " +
				"and CC BY photos (Openverse). Returns up to k results, each with its title, licence and either the SVG text or the photo's " +
				"download, insert and page links, plus a credit line only when the licence requires one; photo thumbnails follow as images. " +
				"The insert link allows downloads from inside apps such as PowerPoint add-ins.",
			inputSchema: IMAGES_INPUT,
			annotations: { ...readOnly, openWorldHint: true }, // it searches open public catalogues
		},
		tracked("find_images", async ({ kind, query, k }) => {
			const q = normalise(query);
			const [key, hit] = await cached(env, ["images", 2, kind, q, k ?? null]); // 2: photo results carry insert_url
			let found: Images;
			if (hit) found = JSON.parse(hit);
			else {
				if (kind === "photo") await spend(true); // only photo searches that miss the cache spend the photo budget
				found = await env.SEARCHER.get(env.SEARCHER.idFromName("global")).images(kind, q, k, key);
			}
			meta.result_count = found.results.length;
			const lines = found.results.map((r, i) => [
				`${i + 1}. ${r.title} | ${r.licence}${r.note ? ` | note: ${r.note}` : ""}${r.thumbnail === undefined ? "" : ` | thumbnail ${r.thumbnail + 1}`}`,
				...(r.credit ? [`   Credit: ${r.credit}`] : []),
				...(r.svg ? [`   SVG: ${r.svg}`] : [`   Download: ${r.download_url}`, ...(r.insert_url ? [`   Insert URL: ${r.insert_url}`] : []), `   Page: ${r.landing_url}`]),
				...(r.creator ? [`   Creator: ${r.creator}`] : []),
				...(r.png_url ? [`   PNG: ${r.png_url}`] : []),
			].join("\n"));
			const summary = [
				lines.length ? lines.join("\n") : `No ${kind}s found.`,
				...(found.unavailable.length ? [`Unavailable right now: ${found.unavailable.join(", ")}.`] : []),
				...(found.thumbnails.length ? ["Thumbnails follow as images, in order: thumbnail 1 first."] : []),
			].join("\n");
			return { content: [text(summary), REMINDER, ...found.thumbnails.map((t) => ({ type: "image" as const, ...t }))] };
		}, deps),
	);

	server.registerTool(
		"submit_feedback",
		{
			title: "Send feedback to eightytwenty",
			description: "Saves one slide correction the user asked to send to eightytwenty as feedback, after they confirmed the summary. " +
				"General terms only: no names, figures or file content.",
			inputSchema: FEEDBACK_INPUT,
			annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: false, openWorldHint: false },
		},
		tracked("submit_feedback", async ({ deck_type, slide_type, deck_style, slide_role, message, correction, reason }) => {
			const since = `${new Date().toISOString().slice(0, 10)}T00:00:00Z`;
			const today = await env.FEEDBACK.prepare("SELECT (SELECT COUNT(*) FROM consulting_feedback WHERE created_at >= ?) + " +
				"(SELECT COUNT(*) FROM stock_pitch_feedback WHERE created_at >= ?) AS n").bind(since, since).first<number>("n");
			if ((today ?? 0) >= env.DAILY_FEEDBACK_BUDGET) {
				meta.errorType = "budget";
				throw new Error("Feedback is full for today. Try again after 00:00 UTC.");
			}
			// plain INSERT: REPLACE would bypass the no-delete trigger
			await env.FEEDBACK.prepare(`INSERT INTO ${deck_type}_feedback (slide_type, deck_style, slide_role, message, correction, reason) VALUES (?, ?, ?, ?, ?, ?)`)
				.bind(slide_type ?? null, deck_style ?? null, slide_role, message, correction, reason || null).run();
			return { content: [text("Saved. Thank you: corrections that recur are reviewed and folded into the playbook.")] };
		}, deps),
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

const limitsOf = (env: Env) => ({ perMinute: env.LIMIT_PER_MINUTE, perMinuteShared: env.LIMIT_PER_MINUTE_SHARED, dailySearchBudget: env.DAILY_SEARCH_BUDGET, dailyPhotoBudget: env.DAILY_PHOTO_BUDGET });

// Every tools/call counts toward the caller's per-minute limit (uncached searches and photo searches also spend a daily budget, in createServer).
async function limit(request: Request, env: Env, body: any, key: string): Promise<Response | null> {
	const calls = [body].flat().filter((m) => m?.method === "tools/call");
	if (!calls.length) return null;
	if (Array.isArray(body)) return rpcError(400, null, "Send one tools/call per request (JSON-RPC batches are not supported).");
	const v = await env.LIMITER.get(env.LIMITER.idFromName("global")).check(key, limitsOf(env));
	return v.ok ? null : rpcError(429, body.id, v.message, { "retry-after": String(v.retryAfter) });
}

// Uncached searches (embedding, vector scan, FTS, rerank, MMR, cache write; flow and image searches too) run here: a Durable Object's CPU
// time is its own, so the Worker stays inside the Free plan's 10 ms per request. The entry exports it bound to the same library.
export const searcher = (lib: Library) => class Searcher extends DurableObject<Env> {
	token: { value?: string; expires?: number } = {}; // the Openverse app token, kept in memory for this instance's lifetime

	search(query: Query, key: string) {
		return uncached(this.env, lib, query, DEFAULT_FLAGS, key);
	}
	flows(query: FlowQuery, key: string) {
		return uncachedFlows(this.env, lib, query, key);
	}
	// An answer with a source unavailable is not cached, so the next call tries that source again.
	async images(kind: Kind, query: string, k: number | undefined, key: string): Promise<Images> {
		const { OPENVERSE_CLIENT_ID: clientId, OPENVERSE_CLIENT_SECRET: clientSecret } = this.env;
		const found = await findImages(kind, query, k, {
			fetch: (input, init) => fetch(input, init), // not the bare global: Workers reject a fetch called on another object
			openverse: clientId && clientSecret ? { clientId, clientSecret } : undefined,
			token: this.token,
		});
		return found.unavailable.length ? found : store(this.env, key, found, lib.manifest.library_version);
	}
};
export type Searcher = InstanceType<ReturnType<typeof searcher>>;

// Set explicitly: a custom domain otherwise gets no Host check and only localhost Origins. localhost serves wrangler dev and the MCP Inspector.
const HOSTS = ["mcp.eightytwenty.tech", "eightytwenty.socratic.workers.dev", "eightytwenty-staging.socratic.workers.dev", "localhost", "127.0.0.1", "[::1]"];

const PAGE_HEADERS = {
	"content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
	"x-content-type-options": "nosniff",
	"referrer-policy": "no-referrer",
};
const PAGES: Record<string, [string, string]> = {
	"/": [docs, "text/html; charset=utf-8"],
	"/docs": [docs, "text/html; charset=utf-8"],
	"/privacy": [privacy, "text/html; charset=utf-8"],
	"/terms": [terms, "text/html; charset=utf-8"],
	"/icon.svg": [icon, "image/svg+xml"],
};

export const app = (lib: Library): ExportedHandler<Env> => ({
	async fetch(request, env, ctx) {
		const { pathname } = new URL(request.url);
		if (pathname === "/mcp") {
			// Before the body is read and the limiter charges the IP: a cross-site page must not put its visitor into cooldown.
			const rejected = hostHeaderValidationResponse(request, HOSTS) ?? originValidationResponse(request, HOSTS);
			if (rejected) return rejected;
			const raw = request.method === "POST" ? await readCapped(request.clone()) : null;
			if (raw === TOO_BIG) return rpcError(413, null, "The request body is over 4 MiB.");
			const body: any = raw === null ? null : (() => { try { return JSON.parse(raw); } catch { return null; } })();
			const key = clientKey(request.headers.get("cf-connecting-ip"));
			const denied = body ? await limit(request, env, body, key) : null;
			if (denied) return denied;
			const hints = { dnt: request.headers.get("dnt") === "1" || request.headers.get("sec-gpc") === "1", userAgent: request.headers.get("user-agent") };
			// One "client connects" event per single initialize message (not a batch); it runs after the response, like tracked().
			// No _meta: initialize is not rate limited, so it must not mint ChatGPT user ids.
			if (body?.method === "initialize")
				ctx.waitUntil(identity(env, key).then((who) => send(env, ctx, hints, initializeEvent(body.params, hints.userAgent, who))).catch(() => {}));
			// Hand the parsed body to the SDK (its parsedBody option); otherwise it clones and parses the body twice more.
			return createMcpHandler(() => createServer(env, lib, key, ctx, hints), { allowedHostnames: HOSTS, allowedOriginHostnames: HOSTS }).fetch(request, body ? { parsedBody: body } : undefined);
		}
		if (pathname === "/.well-known/openai-apps-challenge" && request.method === "GET" && env.OPENAI_APPS_CHALLENGE)
			return new Response(env.OPENAI_APPS_CHALLENGE, { headers: { "content-type": "text/plain; charset=utf-8", ...PAGE_HEADERS } });
		if (pathname === "/.well-known/glama.json" && request.method === "GET" && env.GLAMA_CLAIM)
			return new Response(env.GLAMA_CLAIM, { headers: { "content-type": "application/json; charset=utf-8", ...PAGE_HEADERS } });
		const page = PAGES[pathname];
		if (page && request.method === "GET") return new Response(page[0], { headers: { "content-type": page[1], ...PAGE_HEADERS } });
		return new Response("Not found", { status: 404 });
	},
});
