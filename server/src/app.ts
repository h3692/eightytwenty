// The public connector: three read-only MCP tools at /mcp (stateless Streamable HTTP, default Origin check), the
// Limiter in front of every tool call, and the /docs + /privacy pages. index.ts binds it to the bundled library.
import { McpServer } from "@modelcontextprotocol/server";
import { createMcpHandler } from "agents/mcp/server";
import { z } from "zod";
import labels from "../../pipeline/schema/labels.v1.json";
import anatomyAndTaglines from "../../playbook/anatomy-and-taglines.md";
import archetypes from "../../playbook/archetypes.md";
import attachedDecks from "../../playbook/attached-decks.md";
import distinctiveDesign from "../../playbook/distinctive-design.md";
import qa from "../../playbook/qa.md";
import visualRulesAndDesignOptions from "../../playbook/visual-rules-and-design-options.md";
import workflow from "../../playbook/workflow.md";
import writing from "../../playbook/writing.md";
import docs from "../pages/index.html";
import privacy from "../pages/privacy.html";
import icon from "../pages/icon.svg";
import { search, type Library } from "./search";

export { Limiter } from "./limiter";

const PLAYBOOK: Record<string, string> = {
	workflow,
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
	k: z.number().int().min(1).max(5).optional().describe("How many results, 1 to 5 (default 5)."),
});
const REFERENCE_INPUT = z.object({ id: z.string().regex(/^[A-Za-z0-9-]{1,64}$/, "Use an id exactly as find_references returned it.") });
const PLAYBOOK_INDEX = `Playbook stages (call get_playbook with one of these as \`stage\`):\n${STAGES.map((s) => `- \`${s}\`: ${PLAYBOOK[s].match(/^# (.+)$/m)?.[1] ?? s}`).join("\n")}\n\n${workflow}`;

function createServer(env: Env, lib: Library) {
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
			description: "Search the curated library of slide design DNA by what a slide must do. Returns up to k short summaries " +
				"(id, slide type, purpose, why it works, score). Call get_reference with an id for the full layout. Reference, never copy.",
			inputSchema: FIND_INPUT,
			annotations: readOnly,
		},
		async (args) => {
			const { results, library_version } = await search(env, lib, args);
			if (!results.length)
				return { content: [text(`No references match these filters. Try fewer filters or a broader purpose. (library_version ${library_version})`)] };
			const lines = results.map((r, i) => `${i + 1}. ${r.id} | ${r.slide_type} | score ${r.score}\n   Purpose: ${r.purpose}\n   Why it works: ${r.why_it_works}`);
			return { content: [text(`library_version ${library_version}\n\n${lines.join("\n")}\n\nCall get_reference with an id for its full design DNA and wireframe.`)] };
		},
	);

	server.registerTool(
		"get_reference",
		{
			title: "Get a reference slide",
			description: "The full design-DNA record of one library slide (every region box, colour and type role, text structure) " +
				"plus its wireframe image. Use an id from find_references. Build your own slide from it; never copy it.",
			inputSchema: REFERENCE_INPUT,
			annotations: readOnly,
		},
		async ({ id }) => {
			const dna = await env.DB.prepare("SELECT dna FROM slides WHERE id = ?").bind(id).first<string>("dna");
			if (!dna) return { content: [text(`No reference with id ${id}. Use an id returned by find_references.`)], isError: true };
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

// Every tools/call counts toward the caller's per-minute limit; find_references also spends the daily budget.
async function limit(request: Request, env: Env, body: any): Promise<Response | null> {
	const calls = [body].flat().filter((m) => m?.method === "tools/call");
	if (!calls.length) return null;
	if (Array.isArray(body)) return rpcError(400, null, "Send one tools/call per request (JSON-RPC batches are not supported).");
	const limits = { perMinute: env.LIMIT_PER_MINUTE, perMinuteShared: env.LIMIT_PER_MINUTE_SHARED, dailySearchBudget: env.DAILY_SEARCH_BUDGET };
	const key = clientKey(request.headers.get("cf-connecting-ip"));
	const v = await env.LIMITER.get(env.LIMITER.idFromName("global")).check(key, body.params?.name === "find_references", limits);
	return v.ok ? null : rpcError(429, body.id, v.message, { "retry-after": String(v.retryAfter) });
}

// Drop cached search results from other library builds (they can never be served again).
export const prune = (env: Env, lib: Library) =>
	env.DB.prepare("DELETE FROM search_cache WHERE library_version IS NOT ?").bind(lib.manifest.library_version).run();

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
			const body: any = request.method === "POST" ? await request.clone().json().catch(() => null) : null;
			const denied = body ? await limit(request, env, body) : null;
			if (denied) return denied;
			// Hand the parsed body to the SDK (its parsedBody option); otherwise it clones and parses the body twice more.
			// Bodies without a size or over the SDK's 4 MiB cap are left to the SDK, so it still answers 413.
			const parsed = body && Number(request.headers.get("content-length") ?? Infinity) <= MAX_BODY;
			return createMcpHandler(() => createServer(env, lib)).fetch(request, parsed ? { parsedBody: body } : undefined);
		}
		const page = PAGES[pathname];
		if (page && request.method === "GET") return new Response(page[0], { headers: { "content-type": page[1], ...PAGE_HEADERS } });
		return new Response("Not found", { status: 404 });
	},
	async scheduled(_controller, env) {
		await prune(env, lib);
	},
});
