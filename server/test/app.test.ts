import { env, runInDurableObject } from "cloudflare:test";
import { createExecutionContext, waitOnExecutionContext } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";
import labels from "../../pipeline/schema/labels.v1.json";
import styles from "../../pipeline/schema/style.v1.json";
import archetypesMd from "../../playbook/archetypes.md";
import { app, clientKey, STAGES } from "../src/app";
import type { Limiter } from "../src/limiter";
import { DEFAULT_FLAGS, EMBED_MODEL, RERANK_MODEL, search, searchFlows } from "../src/search";
import { fakeAI, flowFloats, flows, floats, impacts, layouts, library, manifest, rows, seed } from "./fixture";

const lib = library();
const worker = app(lib);
const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3]);
const assets = {
	async fetch(req: Request | string) {
		const path = new URL(typeof req === "string" ? req : req.url).pathname;
		return path === `/wireframes/${rows[0].id}.png` ? new Response(PNG) : new Response("not found", { status: 404 });
	},
};
const testEnv = (over: Record<string, unknown> = {}) => ({ ...env, AI: fakeAI(() => floats[0]) as unknown as Ai, ASSETS: assets as unknown as Fetcher, ...over }) as Env;

let ip = 0; // a fresh client IP per test, so per-key counters never leak between tests
const nextIp = () => `203.0.113.${++ip}`;

async function call(path: string, init: RequestInit = {}, e = testEnv()) {
	const ctx = createExecutionContext();
	const res = await worker.fetch!(new Request(`https://eightytwenty.test${path}`, init) as any, e, ctx);
	await waitOnExecutionContext(ctx);
	return res;
}

// One JSON-RPC message to /mcp; returns the HTTP response and the parsed JSON-RPC reply (SSE or JSON).
async function rpc(method: string, params: unknown = {}, { headers = {}, e = testEnv(), from = nextIp() }: { headers?: Record<string, string>; e?: Env; from?: string } = {}) {
	const res = await call("/mcp", {
		method: "POST",
		headers: { "content-type": "application/json", accept: "application/json, text/event-stream", "mcp-protocol-version": "2025-06-18", "cf-connecting-ip": from, ...headers },
		body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
	}, e);
	const text = await res.text();
	const data = text.includes("data:") ? text.split("\n").filter((l) => l.startsWith("data:")).map((l) => l.slice(5)).join("") : text;
	return { res, body: data ? JSON.parse(data) : null };
}
const tool = (name: string, args: Record<string, unknown> = {}, opts?: Parameters<typeof rpc>[2]) => rpc("tools/call", { name, arguments: args }, opts);

// The Searcher Durable Object runs uncached searches with its own env: give it the same stand-in AI as testEnv().
const searcher = () => env.SEARCHER.get(env.SEARCHER.idFromName("global"));
const searcherAI = (ai: ReturnType<typeof fakeAI>) => runInDurableObject<Rpc.DurableObjectBranded, void>(searcher(), (s: any) => { s.env = { ...s.env, AI: ai }; });

beforeEach(async () => {
	await seed(env.DB);
	await searcherAI(fakeAI(() => floats[0]));
});

describe("MCP endpoint", () => {
	it("initializes statelessly", async () => {
		const { res, body } = await rpc("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "test", version: "1" } });
		expect(res.status).toBe(200);
		expect(res.headers.get("mcp-session-id")).toBeNull();
		expect(body.result.serverInfo.name).toBe("eightytwenty");
	});

	it("lists four read-only, titled tools with enum filters from the label schema", async () => {
		const { body } = await rpc("tools/list");
		const tools = Object.fromEntries(body.result.tools.map((t: any) => [t.name, t]));
		expect(Object.keys(tools).sort()).toEqual(["find_deck_flows", "find_references", "get_playbook", "get_reference"]);
		for (const t of Object.values<any>(tools)) {
			expect(t.title).toBeTruthy();
			expect(t.annotations).toMatchObject({ readOnlyHint: true, destructiveHint: false });
		}
		const p = tools.find_references.inputSchema.properties;
		expect(p.slide_type.enum).toEqual(labels.properties.archetype.enum);
		expect(p.slide_type.enum).toHaveLength(17);
		expect(p.industry.enum).toEqual(labels.properties.industry.enum);
		expect(p.data_type.enum).toEqual(labels.properties.data_type.enum);
		expect(p.k.maximum).toBe(8);
		expect(p.impact.enum).toEqual(["none", "build", "spotlight", "shade_ribbon", "repeat"]);
		expect(p.style.enum).toEqual(styles.properties.style.enum);
		expect(p.style.description).toBeTruthy();
		expect(tools.find_references.description).toMatch(/one per deck/i);
		expect(tools.find_references.description).toMatch(/impact filter returns few/i);
		// when to use them leads each search description; refusal wording stays out of tool descriptions
		for (const t of [tools.find_references, tools.find_deck_flows]) {
			expect(t.description.split(". ")[0]).toMatch(/after .*(claim|end belief).* settled.*get_playbook/i);
			expect(t.description).not.toMatch(/can't be used/i);
		}
		expect(tools.find_references.inputSchema.required).toEqual(["purpose"]);
		expect(tools.get_playbook.inputSchema.properties.stage.enum).toEqual(STAGES);
		expect(tools.get_playbook.description).toMatch(/before planning a deck/i);
		const f = tools.find_deck_flows.inputSchema;
		expect(f.properties.industry.enum).toEqual(labels.properties.industry.enum);
		expect(f.properties.length.enum).toEqual(["short", "medium", "long"]);
		expect(f.properties.style.enum).toEqual(styles.properties.style.enum);
		expect(f.properties.style.description).toBeTruthy();
		expect(f.required).toEqual(["purpose"]);
		expect(tools.find_deck_flows.description).toMatch(/whole deck/i);
	});

	it("answers newer MCP methods (server/discover, subscriptions/listen) without a server error", async () => {
		for (const m of ["server/discover", "subscriptions/listen"]) {
			const { res, body } = await rpc(m);
			expect(res.status).toBeLessThan(500);
			expect(body.jsonrpc).toBe("2.0");
		}
	});

	it("answers concurrent tool calls independently (schemas are shared per isolate, servers are not)", async () => {
		const one = async (stage: string) => (await tool("get_playbook", { stage })).body.result;
		const expected = [];
		for (const stage of STAGES) expected.push(await one(stage));
		const [bad, ...concurrent] = await Promise.all([one("nope"), ...STAGES.map(one)]);
		expect(bad.isError).toBe(true);
		expect(concurrent).toEqual(expected);
		expect(new Set(concurrent.map((r) => r.content[0].text)).size).toBe(STAGES.length);
	});

	it("leaves malformed and oversized bodies to the SDK (parse error, 413)", async () => {
		const headers = { "content-type": "application/json", accept: "application/json, text/event-stream", "mcp-protocol-version": "2025-06-18" };
		const bad = await call("/mcp", { method: "POST", headers, body: "{not json" });
		expect(bad.status).toBe(400);
		expect((await bad.json<any>()).error.code).toBe(-32700);
		const big = JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "get_playbook", arguments: { pad: "x".repeat(4 * 1024 * 1024) } } });
		expect((await call("/mcp", { method: "POST", headers: { ...headers, "cf-connecting-ip": nextIp() }, body: big })).status).toBe(413);
	});

	it("rejects a foreign browser Origin with 403 and accepts requests without an Origin", async () => {
		expect((await rpc("tools/list", {}, { headers: { origin: "https://evil.example" } })).res.status).toBe(403);
		expect((await rpc("tools/list")).res.status).toBe(200);
	});
});

describe("server instructions and prompts", () => {
	it("sends instructions on initialize: scope and the questions, plan, approval, build order up front", async () => {
		const { body } = await rpc("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "test", version: "1" } });
		const ins: string = body.result.instructions;
		expect(ins.length).toBeLessThan(2000);
		const head = ins.slice(0, 512);
		for (const s of ["researching and building decks", "get_playbook", "one per message", "approve", "eightytwenty can't be used for that"])
			expect(head).toContain(s);
		expect(ins).toMatch(/never as slides/i);
	});

	it("offers a start prompt that opens the guided flow, with optional context", async () => {
		const { body: list } = await rpc("prompts/list");
		const start = list.result.prompts.find((p: { name: string }) => p.name === "start");
		expect(start.description).toBeTruthy();
		expect(start.arguments).toEqual([expect.objectContaining({ name: "context", required: false })]);
		const { body } = await rpc("prompts/get", { name: "start", arguments: { context: "a pitch for a campus food startup" } });
		const msg = body.result.messages[0];
		expect(msg.role).toBe("user");
		for (const s of ["a pitch for a campus food startup", "get_playbook", "one at a time", "approve"]) expect(msg.content.text).toContain(s);
		const { body: bare } = await rpc("prompts/get", { name: "start", arguments: {} });
		expect(bare.result.messages[0].content.text).toContain("get_playbook");
	});

	it("does not count prompts against the tool-call limit", async () => {
		const e = testEnv({ LIMIT_PER_MINUTE: 1 }), from = nextIp();
		for (let i = 0; i < 3; i++) expect((await rpc("prompts/get", { name: "start", arguments: {} }, { e, from })).res.status).toBe(200);
	});
});

describe("get_playbook", () => {
	it("bundles one stage per playbook chapter", () => {
		expect([...STAGES].sort()).toEqual(env.PLAYBOOK_FILES.map((f: string) => f.replace(/\.md$/, "")).sort());
	});

	it("archetypes.md lists exactly the label schema's slide types", () => {
		const ids = [...archetypesMd.matchAll(/^\| `([a-z-]+)` \|/gm)].map((m) => m[1]);
		expect(ids).toEqual(labels.properties.archetype.enum);
	});

	it("with no stage returns the stage index and the workflow chapter", async () => {
		const { body } = await tool("get_playbook");
		const text = body.result.content[0].text;
		for (const s of STAGES) expect(text).toContain(s);
		expect(text).toContain("# Workflow");
	});

	it("the workflow puts scope, one question per message, a text plan and approval before any build", async () => {
		const { body } = await tool("get_playbook");
		const text = body.result.content[0].text;
		for (const s of ["eightytwenty can't be used for that.", "One question per message", "Reply **approve**", "Nothing extra in the deck", "Research to-do, in chat"])
			expect(text).toContain(s);
		expect(text).not.toMatch(/hidden \*\*Research To-Do\*\* slide|Design Options slide \(hidden\)/);
		for (const stage of STAGES) {  // no chapter sends anything into the deck or skips the plan
			const chapter = (await tool("get_playbook", { stage })).body.result.content[0].text;
			expect(chapter, stage).not.toMatch(/Design Options (slide|asset list)|rough layout/i);
			if (stage !== "polish") expect(chapter, stage).not.toMatch(/`[^`\n]*(->|→|=>)[^`\n]*`/); // example slide text never carries an arrow
		}
		expect(text).toMatch(/only when the user explicitly asks for everything at once/i);
		expect(text).toMatch(/If a style filter returns nothing, search again without it/);
		const polish = (await tool("get_playbook", { stage: "polish" })).body.result.content[0].text;
		expect(polish).toContain("# Density and polish");
		expect(polish).toMatch(/No arrow characters/);
	});

	it("returns one chapter", async () => {
		const { body } = await tool("get_playbook", { stage: "archetypes" });
		expect(body.result.content[0].text).toBe(archetypesMd);
	});

	it("rejects an unknown stage", async () => {
		const { body } = await tool("get_playbook", { stage: "nope" });
		expect(body.result?.isError ?? !!body.error).toBe(true);
		expect(JSON.stringify(body)).toContain("archetypes");
	});
});

describe("find_references", () => {
	it("returns text summaries and the library_version, never vectors", async () => {
		const { body } = await tool("find_references", { purpose: "market share of competitors over time", k: 2 });
		const text: string = body.result.content.map((c: any) => c.text).join("\n");
		expect(body.result.isError).toBeFalsy();
		expect(text).toContain(rows[0].id);
		expect(text).toContain(rows[0].archetype);
		expect(text).toContain(rows[0].purpose);
		expect(text).toContain(rows[0].why_it_works);
		expect(text).toMatch(/score \d/);
		expect(text).toContain(manifest.library_version);
		expect(text).toContain("get_reference");
		expect(text).not.toMatch(/-?\d+(,-?\d+){50}/);
	});

	it("shows each result's component kinds and its impact when it is an impact slide", async () => {
		await searcherAI(fakeAI(() => floats[0], (_, t) => t.map((x) => (x.includes("customer journey") ? 0.9 : 0.1)))); // row 9 over row 8 in deck4
		const { body } = await tool("find_references", { purpose: "market share", k: 8 });
		const text: string = body.result.content[0].text;
		expect(text).toContain(`${rows[9].id} | ${rows[9].archetype} | score`);
		expect(text).toContain("   Kinds: tracker×5, kpi_row×2, takeaway\n");
		expect(text).toContain(`   Kinds: tracker×5, kpi_row×${(9 % 3) + 2}, takeaway | impact: shade_ribbon\n`);
		expect(text).not.toContain("impact: none");
		expect(text).toContain(`takeaway | impact: shade_ribbon\n   Style: ${rows[9].style} | When to use: ${rows[9].when_to_use}\n`);
		const spot = await tool("find_references", { purpose: "market share", impact: "spotlight" });
		expect(spot.body.result.content[0].text.split("\n").filter((l: string) => /^\d\. /.test(l))).toEqual([expect.stringContaining(rows[6].id)]);
	});

	it("filters by style and rejects an unknown one with the valid values", async () => {
		const { body } = await tool("find_references", { purpose: "market share", style: "data-led" });
		expect(body.result.content[0].text.split("\n").filter((l: string) => /^\d\. /.test(l))).toEqual([expect.stringContaining(rows[6].id)]);
		const bad = await tool("find_references", { purpose: "x", style: "flashy" });
		expect(bad.body.result?.isError ?? !!bad.body.error).toBe(true);
		expect(JSON.stringify(bad.body)).toContain("minimal-editorial");
	});

	it("accepts k up to 8 and rejects an unknown impact", async () => {
		expect((await tool("find_references", { purpose: "x", k: 9 })).body.result?.isError ?? true).toBe(true);
		const { body } = await tool("find_references", { purpose: "x", impact: "glow" });
		expect(body.result?.isError ?? !!body.error).toBe(true);
		expect(JSON.stringify(body)).toContain("shade_ribbon");
	});

	it("rejects an unknown slide_type with the valid values", async () => {
		const { body } = await tool("find_references", { purpose: "x", slide_type: "pie" });
		expect(body.result?.isError ?? !!body.error).toBe(true);
		expect(JSON.stringify(body)).toContain("executive-summary");
	});

	it("says what to change when nothing matches", async () => {
		const { body } = await tool("find_references", { purpose: "anything", slide_type: "hook" });
		expect(body.result.content[0].text).toMatch(/No references match/);
	});
});

describe("find_deck_flows", () => {
	it("returns up to 3 flow summaries and the library_version, from the Searcher, cached", async () => {
		const ai = fakeAI(() => flowFloats[1]);
		await searcherAI(ai);
		const noAI = { run: () => { throw new Error("the Worker must not call Workers AI"); } };
		const { body } = await tool("find_deck_flows", { purpose: "Win over the judges" }, { e: testEnv({ AI: noAI }) });
		expect(body.result.isError).toBeFalsy();
		expect(ai.calls.map((c) => c.model)).toEqual([EMBED_MODEL]);
		const text: string = body.result.content[0].text;
		const { results } = await searchFlows(testEnv({ AI: fakeAI(() => flowFloats[1]) }), lib, { purpose: "win over the judges" });
		expect(results).toHaveLength(3);
		expect(results[0].id).toBe(flows[1].id);
		expect(text.split("\n").filter((l) => /^\d\. /.test(l))).toEqual(results.map((r, i) => `${i + 1}. ${r.id} | ${r.arc} | ${r.length} deck | ${r.industry} | ${r.style} style | score ${r.score}`));
		for (const s of [manifest.library_version, "Sections: cover > solution > financials", `Why the flow works: ${flows[1].why_the_flow_works}`, "get_reference"]) expect(text).toContain(s);
		const cached = await env.DB.prepare("SELECT results FROM search_cache").all<{ results: string }>();
		expect(cached.results.map((r) => JSON.parse(r.results))).toEqual([results]);
	});

	it("filters by style", async () => {
		const { body } = await tool("find_deck_flows", { purpose: "x", style: "bold-pitch" });
		expect(body.result.content[0].text.split("\n").filter((l: string) => /^\d\. /.test(l))).toEqual([expect.stringContaining(`${flows[1].id} | pillars | medium deck | technology | bold-pitch style |`)]);
	});

	it("rejects an unknown length with the valid values", async () => {
		const { body } = await tool("find_deck_flows", { purpose: "x", length: "huge" });
		expect(body.result?.isError ?? !!body.error).toBe(true);
		expect(JSON.stringify(body)).toContain("medium");
	});

	it("says what to change when nothing matches", async () => {
		const { body } = await tool("find_deck_flows", { purpose: "x", industry: "automotive" });
		expect(body.result.content[0].text).toMatch(/No deck flows match/);
	});

	it("refuses with a clear error when D1 has no matching flows table, and slide tools keep working", async () => {
		await env.DB.prepare("DROP TABLE flows").run();
		const { body } = await tool("find_deck_flows", { purpose: "x" });
		expect(body.result.isError).toBe(true);
		expect(body.result.content[0].text).toMatch(/flows.*records\.sql/);
		expect((await tool("find_references", { purpose: "market share" })).body.result.isError).toBeFalsy();
		expect((await tool("get_reference", { id: rows[1].id })).body.result.isError).toBeFalsy();
	});
});

describe("Searcher Durable Object", () => {
	const q = { purpose: "Market share of competitors  over time", k: 3 };

	it("returns exactly what the in-Worker search returns", async () => {
		const direct = await search(testEnv(), lib, q, { ...DEFAULT_FLAGS, cache: false });
		expect(direct.results).toHaveLength(3);
		expect(await searcher().search({ ...q, purpose: "market share of competitors over time" }, "")).toEqual(direct);
	});

	it("runs the uncached search for find_references, so the Worker never calls Workers AI, and caches it", async () => {
		const ai = fakeAI(() => floats[0]);
		await searcherAI(ai);
		const noAI = { run: () => { throw new Error("the Worker must not call Workers AI"); } };
		const { body } = await tool("find_references", q, { e: testEnv({ AI: noAI }) });
		expect(body.result.isError).toBeFalsy();
		expect(ai.calls.map((c) => c.model)).toEqual([EMBED_MODEL, RERANK_MODEL]);
		const { results } = await search(testEnv(), lib, q, { ...DEFAULT_FLAGS, cache: false });
		const lines = results.map((r, i) => `${i + 1}. ${r.id} | ${r.slide_type} | score ${r.score}`);
		expect(body.result.content[0].text.split("\n").filter((l: string) => /^\d\. /.test(l))).toEqual(lines);
		const cached = await env.DB.prepare("SELECT results, library_version FROM search_cache").all<{ results: string; library_version: string }>();
		expect(cached.results.map((r) => [JSON.parse(r.results), r.library_version])).toEqual([[results, manifest.library_version]]);
	});

	it("is not called on a cache hit: the Worker serves it from D1", async () => {
		const first = await tool("find_references", q);
		const noDO = { idFromName: () => { throw new Error("Searcher called on a cache hit"); } };
		const again = await tool("find_references", q, { e: testEnv({ SEARCHER: noDO }) });
		expect(again.body.result).toEqual(first.body.result);
	});

	it("returns its errors as the same tool error as the in-Worker search", async () => {
		await seed(env.DB, "bge-m3/desc-v1/other");
		const expected = await search(testEnv(), lib, q).then(() => "no error", (e: Error) => e.message);
		expect(expected).toMatch(/D1 holds library_version bge-m3\/desc-v1\/other/);
		const { body } = await tool("find_references", q);
		expect(body.result.isError).toBe(true);
		expect(body.result.content).toEqual([{ type: "text", text: expected }]);
	});
});

describe("get_reference", () => {
	it("returns the labels, v3 layout and design DNA as JSON, and the mockup image", async () => {
		const { body } = await tool("get_reference", { id: rows[0].id });
		const [text, image] = body.result.content;
		expect(JSON.parse(text.text)).toEqual({ ...rows[0], impact: impacts[0], layout: layouts[0] });
		expect(image).toMatchObject({ type: "image", mimeType: "image/png" });
		expect(Uint8Array.from(atob(image.data), (c) => c.charCodeAt(0))).toEqual(PNG);
	});

	it("still returns the JSON when the wireframe is missing", async () => {
		const { body } = await tool("get_reference", { id: rows[1].id });
		expect(body.result.content).toHaveLength(1);
		expect(JSON.parse(body.result.content[0].text).id).toBe(rows[1].id);
	});

	it("returns a deck flow for a deck id, marking each step's slide as available or not", async () => {
		const { body } = await tool("get_reference", { id: flows[0].id });
		expect(body.result.isError).toBeFalsy();
		expect(body.result.content).toHaveLength(1);
		const flow = JSON.parse(body.result.content[0].text);
		expect(flow).toEqual({ ...flows[0].record, steps: flows[0].record.steps.map((s, k) => ({ ...s, available: k < 2 })) });
	});

	it("rejects an unknown deck id with a hint", async () => {
		const { body } = await tool("get_reference", { id: "ffffffffffffffff" });
		expect(body.result.isError).toBe(true);
		expect(body.result.content[0].text).toMatch(/No deck flow.*find_deck_flows/);
	});

	it("rejects an unknown id with a hint", async () => {
		const { body } = await tool("get_reference", { id: "0000000000000000-01" });
		expect(body.result.isError).toBe(true);
		expect(body.result.content[0].text).toMatch(/No reference.*find_references/);
	});
});

describe("rate limits", () => {
	it("cools a client down with 429 after the per-minute limit, other clients unaffected", async () => {
		const e = testEnv({ LIMIT_PER_MINUTE: 3 }), from = nextIp();
		for (let i = 0; i < 3; i++) expect((await tool("get_playbook", {}, { e, from })).res.status).toBe(200);
		const { res, body } = await tool("get_playbook", {}, { e, from });
		expect(res.status).toBe(429);
		expect(res.headers.get("retry-after")).toBe("60");
		expect(body.error.message).toBe("Slow down: too many requests. Try again in 1 minute.");
		expect((await tool("get_playbook", {}, { e })).res.status).toBe(200);
	});

	it("does not count non-tool requests", async () => {
		const e = testEnv({ LIMIT_PER_MINUTE: 1 }), from = nextIp();
		for (let i = 0; i < 3; i++) expect((await rpc("tools/list", {}, { e, from })).res.status).toBe(200);
	});

	it("spends the daily search budget only on uncached searches, after validation", async () => {
		// The global Limiter keeps today's count from earlier tests: allow exactly two more searches.
		const used = await runInDurableObject(env.LIMITER.get(env.LIMITER.idFromName("global")), (l: Limiter) =>
			l.sql.exec<{ used: number }>("SELECT used FROM budget").toArray()[0]?.used ?? 0);
		const e = testEnv({ DAILY_SEARCH_BUDGET: used + 2 });
		expect((await tool("get_playbook", {}, { e })).body.result.isError).toBeFalsy();
		expect((await tool("get_reference", { id: flows[0].id }, { e })).body.result.isError).toBeFalsy();
		expect((await tool("find_references", { purpose: "market share", k: 9 }, { e })).body.result.isError).toBe(true);
		for (let i = 0; i < 2; i++) expect((await tool("find_references", { purpose: "market share" }, { e })).body.result.content[0].text).toMatch(/^library_version/); // one miss, one hit
		expect((await tool("find_deck_flows", { purpose: "win" }, { e })).body.result.isError).toBeFalsy();
		for (const [name, args] of [["find_references", { purpose: "pricing tiers" }], ["find_deck_flows", { purpose: "launch" }]] as const) {
			const { res, body } = await tool(name, args, { e });
			expect(res.status).toBe(200);
			expect(body.result).toMatchObject({ isError: true, content: [{ text: "The shared daily search budget is used up. Try again after 00:00 UTC." }] });
		}
	});

	it("reads a body without a declared size only up to 4 MiB: small ones work, bigger ones get 413", async () => {
		const send = (bytes: Uint8Array) => call("/mcp", {
			method: "POST", headers: { "content-type": "application/json", accept: "application/json, text/event-stream", "cf-connecting-ip": nextIp() },
			body: new ReadableStream({ start(c) { for (let i = 0; i < bytes.length; i += 65_536) c.enqueue(bytes.subarray(i, i + 65_536)); c.close(); } }), duplex: "half",
		} as RequestInit);
		const small = new TextEncoder().encode(JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list", params: {} }));
		expect((await send(small)).status).toBe(200);
		const big = new TextEncoder().encode(JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list", params: { pad: "x".repeat(5 * 1024 * 1024) } }));
		const res = await send(big);
		expect(res.status).toBe(413);
		expect((await res.json() as any).error.code).toBe(-32000);
	});
});

describe("clientKey", () => {
	it("puts Anthropic egress ranges in one shared bucket", () => {
		expect(clientKey("160.79.104.1")).toBe("anthropic");
		expect(clientKey("160.79.111.254")).toBe("anthropic");
		expect(clientKey("153.61.208.9")).toBe("anthropic");
		expect(clientKey("153.61.223.255")).toBe("anthropic");
		expect(clientKey("160.79.112.1")).toBe("160.79.112.1");
		expect(clientKey("153.61.224.1")).toBe("153.61.224.1");
	});

	it("keys IPv6 clients by /64, so rotating the interface id does not escape the limit", () => {
		expect(clientKey("2001:db8:1:2::5")).toBe("2001:db8:1:2::/64");
		expect(clientKey("2001:0db8:0001:0002:aaaa:bbbb:cccc:dddd")).toBe("2001:db8:1:2::/64");
		expect(clientKey("::1")).toBe("0:0:0:0::/64");
	});

	it("falls back to one bucket when the IP is missing", () => {
		expect(clientKey(null)).toBe("unknown");
	});
});

describe("tool descriptions", () => {
	it("point the impact filter at requests to emphasize a key point", async () => {
		const { body } = await rpc("tools/list");
		const find = body.result.tools.find((t: { name: string }) => t.name === "find_references");
		expect(find.inputSchema.properties.impact.description).toMatch(/emphasi[sz]e/);
	});
});

describe("Limiter", () => {
	const limits = { perMinute: 2, perMinuteShared: 5, dailySearchBudget: 100 };
	const inDO = <T>(fn: (l: Limiter, state: DurableObjectState) => T) => runInDurableObject(env.LIMITER.get(env.LIMITER.newUniqueId()), fn);

	it("escalates cooldowns for repeat offenders: 1, 2, 4 minutes", async () => {
		await inDO((l) => {
			let t = 0;
			const burst = () => { for (let i = 0; i < 2; i++) expect(l.check("k", limits, t).ok).toBe(true); return l.check("k", limits, t); };
			expect(burst().message).toMatch(/in 1 minute\.$/);
			t += 61_000;
			expect(burst().message).toMatch(/in 2 minutes\.$/);
			expect(l.check("k", limits, t + 60_000).message).toMatch(/in 1 minute\.$/); // still cooling down
			t += 121_000;
			expect(burst().message).toMatch(/in 4 minutes\.$/);
		});
	});

	it("gives the shared anthropic bucket the higher limit", async () => {
		await inDO((l) => {
			for (let i = 0; i < 5; i++) expect(l.check("anthropic", limits, 0).ok).toBe(true);
			expect(l.check("anthropic", limits, 0).ok).toBe(false);
		});
	});

	it("counts the daily budget per UTC day", async () => {
		await inDO((l) => {
			const b = { ...limits, dailySearchBudget: 1 }, day = 86_400_000;
			expect(l.spend("a", b, 0).ok).toBe(true);
			expect(l.spend("b", b, 1000).message).toMatch(/daily search budget/);
			expect(l.spend("b", b, day).ok).toBe(true);
		});
	});

	it("keeps a tenth of the daily budget out of the shared anthropic bucket's reach", async () => {
		await inDO((l) => {
			const b = { ...limits, dailySearchBudget: 10 };
			for (let i = 0; i < 9; i++) expect(l.spend("anthropic", b, 0).ok).toBe(true);
			expect(l.spend("anthropic", b, 0).message).toMatch(/daily search budget/);
			expect(l.spend("198.51.100.7", b, 0).ok).toBe(true);
			expect(l.spend("198.51.100.7", b, 0).ok).toBe(false);
		});
	});

	it("forgets a client 24 hours after its last request", async () => {
		await inDO((l) => {
			l.check("old", limits, 0);
			l.check("new", limits, 86_400_000 + 120_000);
			const keys = l.sql.exec<{ key: string }>("SELECT key FROM keys").toArray().map((r) => r.key);
			expect(keys).toEqual(["new"]);
			expect(l.sql.exec("SELECT day FROM budget").toArray().length).toBeLessThanOrEqual(1);
		});
	});

	it("deletes idle clients on an alarm even when no other request arrives", async () => {
		await inDO(async (l, state) => {
			const day = 86_400_000, now = Date.now();
			l.check("idle", limits, now - day - 1000);
			l.check("recent", limits, now - 1000);
			expect(await state.storage.getAlarm()).not.toBeNull();
			await l.alarm();
			expect(l.sql.exec<{ key: string }>("SELECT key FROM keys").toArray().map((r) => r.key)).toEqual(["recent"]);
			expect(await state.storage.getAlarm()).toBe(now - 1000 + day); // next: when "recent" turns 24 h old
		});
	});
});

describe("pages", () => {
	it.each([["/"], ["/docs"]])("%s documents the tools and how to connect", async (path) => {
		const res = await call(path);
		expect(res.status).toBe(200);
		expect(res.headers.get("content-type")).toMatch(/^text\/html/);
		const html = await res.text();
		for (const s of ["get_playbook", "find_references", "find_deck_flows", "get_reference", "/mcp", "claude.ai", "Claude Code"]) expect(html).toContain(s);
	});

	it("/privacy states what is sent and kept", async () => {
		const html = await (await call("/privacy")).text();
		for (const s of ["rate limit", "24 hours", "cookies", "accounts", "logged"]) expect(html.toLowerCase()).toContain(s);
	});

	it("serves an icon and sets a strict CSP with no external assets", async () => {
		const res = await call("/icon.svg");
		expect(res.headers.get("content-type")).toBe("image/svg+xml");
		const csp = (await call("/")).headers.get("content-security-policy");
		expect(csp).toContain("default-src 'none'");
	});

	it("never serves library files over a public URL", async () => {
		for (const p of [`/wireframes/${rows[0].id}.png`, "/vecs.bin", "/norms.bin", "/manifest.json", "/records.sql"])
			expect((await call(p)).status).toBe(404);
	});
});
