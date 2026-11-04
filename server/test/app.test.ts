import { env, runInDurableObject } from "cloudflare:test";
import { createExecutionContext, waitOnExecutionContext } from "cloudflare:test";
import { beforeEach, describe, expect, it } from "vitest";
import labels from "../../pipeline/schema/labels.v1.json";
import archetypesMd from "../../playbook/archetypes.md";
import { app, clientKey, prune, STAGES } from "../src/app";
import type { Limiter } from "../src/limiter";
import { fakeAI, floats, library, manifest, rows, seed } from "./fixture";

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

beforeEach(() => seed(env.DB));

describe("MCP endpoint", () => {
	it("initializes statelessly", async () => {
		const { res, body } = await rpc("initialize", { protocolVersion: "2025-06-18", capabilities: {}, clientInfo: { name: "test", version: "1" } });
		expect(res.status).toBe(200);
		expect(res.headers.get("mcp-session-id")).toBeNull();
		expect(body.result.serverInfo.name).toBe("eightytwenty");
	});

	it("lists three read-only, titled tools with enum filters from the label schema", async () => {
		const { body } = await rpc("tools/list");
		const tools = Object.fromEntries(body.result.tools.map((t: any) => [t.name, t]));
		expect(Object.keys(tools).sort()).toEqual(["find_references", "get_playbook", "get_reference"]);
		for (const t of Object.values<any>(tools)) {
			expect(t.title).toBeTruthy();
			expect(t.annotations).toMatchObject({ readOnlyHint: true, destructiveHint: false });
		}
		const p = tools.find_references.inputSchema.properties;
		expect(p.slide_type.enum).toEqual(labels.properties.archetype.enum);
		expect(p.slide_type.enum).toHaveLength(17);
		expect(p.industry.enum).toEqual(labels.properties.industry.enum);
		expect(p.data_type.enum).toEqual(labels.properties.data_type.enum);
		expect(p.k.maximum).toBe(5);
		expect(tools.find_references.inputSchema.required).toEqual(["purpose"]);
		expect(tools.get_playbook.inputSchema.properties.stage.enum).toEqual(STAGES);
		expect(tools.get_playbook.description).toMatch(/before planning a deck/i);
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

describe("get_reference", () => {
	it("returns the design-DNA JSON and the wireframe image", async () => {
		const { body } = await tool("get_reference", { id: rows[0].id });
		const [text, image] = body.result.content;
		expect(JSON.parse(text.text)).toEqual(rows[0]);
		expect(image).toMatchObject({ type: "image", mimeType: "image/png" });
		expect(Uint8Array.from(atob(image.data), (c) => c.charCodeAt(0))).toEqual(PNG);
	});

	it("still returns the JSON when the wireframe is missing", async () => {
		const { body } = await tool("get_reference", { id: rows[1].id });
		expect(body.result.content).toHaveLength(1);
		expect(JSON.parse(body.result.content[0].text).id).toBe(rows[1].id);
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
		expect(body.error.message).toBe("Slow down: too many searches. Try again in 1 minute.");
		expect((await tool("get_playbook", {}, { e })).res.status).toBe(200);
	});

	it("does not count non-tool requests", async () => {
		const e = testEnv({ LIMIT_PER_MINUTE: 1 }), from = nextIp();
		for (let i = 0; i < 3; i++) expect((await rpc("tools/list", {}, { e, from })).res.status).toBe(200);
	});

	it("only find_references spends the daily search budget", async () => {
		const e = testEnv({ DAILY_SEARCH_BUDGET: 0 });
		expect((await tool("get_playbook", {}, { e })).res.status).toBe(200);
		const { res, body } = await tool("find_references", { purpose: "market share" }, { e });
		expect(res.status).toBe(429);
		expect(body.error.message).toBe("The shared daily search budget is used up. Try again after 00:00 UTC.");
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

describe("Limiter", () => {
	const limits = { perMinute: 2, perMinuteShared: 5, dailySearchBudget: 100 };
	const inDO = <T>(fn: (l: Limiter, state: DurableObjectState) => T) => runInDurableObject(env.LIMITER.get(env.LIMITER.newUniqueId()), fn);

	it("escalates cooldowns for repeat offenders: 1, 2, 4 minutes", async () => {
		await inDO((l) => {
			let t = 0;
			const burst = () => { for (let i = 0; i < 2; i++) expect(l.check("k", false, limits, t).ok).toBe(true); return l.check("k", false, limits, t); };
			expect(burst().message).toMatch(/in 1 minute\.$/);
			t += 61_000;
			expect(burst().message).toMatch(/in 2 minutes\.$/);
			expect(l.check("k", false, limits, t + 60_000).message).toMatch(/in 1 minute\.$/); // still cooling down
			t += 121_000;
			expect(burst().message).toMatch(/in 4 minutes\.$/);
		});
	});

	it("gives the shared anthropic bucket the higher limit", async () => {
		await inDO((l) => {
			for (let i = 0; i < 5; i++) expect(l.check("anthropic", false, limits, 0).ok).toBe(true);
			expect(l.check("anthropic", false, limits, 0).ok).toBe(false);
		});
	});

	it("counts the daily budget per UTC day", async () => {
		await inDO((l) => {
			const b = { ...limits, dailySearchBudget: 1 }, day = 86_400_000;
			expect(l.check("a", true, b, 0).ok).toBe(true);
			expect(l.check("b", true, b, 1000).message).toMatch(/daily search budget/);
			expect(l.check("b", false, b, 1000).ok).toBe(true);
			expect(l.check("b", true, b, day).ok).toBe(true);
		});
	});

	it("forgets a client 24 hours after its last request", async () => {
		await inDO((l) => {
			l.check("old", false, limits, 0);
			l.check("new", false, limits, 86_400_000 + 120_000);
			const keys = l.sql.exec<{ key: string }>("SELECT key FROM keys").toArray().map((r) => r.key);
			expect(keys).toEqual(["new"]);
			expect(l.sql.exec("SELECT day FROM budget").toArray().length).toBeLessThanOrEqual(1);
		});
	});

	it("deletes idle clients on an alarm even when no other request arrives", async () => {
		await inDO(async (l, state) => {
			const day = 86_400_000, now = Date.now();
			l.check("idle", false, limits, now - day - 1000);
			l.check("recent", false, limits, now - 1000);
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
		for (const s of ["get_playbook", "find_references", "get_reference", "/mcp", "claude.ai", "Claude Code"]) expect(html).toContain(s);
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

describe("cache hygiene", () => {
	it("prunes cached results of other library versions", async () => {
		await tool("find_references", { purpose: "market share" });
		await env.DB.prepare("INSERT INTO search_cache (key, results, library_version) VALUES ('old', '[]', 'bge-m3/desc-v1/old')").run();
		await prune(env, lib);
		const left = await env.DB.prepare("SELECT library_version FROM search_cache").all<{ library_version: string }>();
		expect(left.results.map((r) => r.library_version)).toEqual([manifest.library_version]);
	});
});
