import { afterEach, describe, expect, it, vi } from "vitest";
import { clientName, send, SERVER_VERSION, toolEvent, tracked } from "../src/analytics";

const CLIENT = { name: "claude-ai", version: "0.1.0" };
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

// A fake ExecutionContext: collects waitUntil work so each test awaits it (an unhandled rejection fails the run).
function fakeCtx() {
	const pending: Promise<unknown>[] = [];
	return { pending, waitUntil: (p: Promise<unknown>) => void pending.push(p), settle: () => Promise.all(pending) };
}

let fetched: { url: string; init?: RequestInit }[];
function spyFetch(respond: () => Promise<Response> = async () => new Response(null, { status: 200 })) {
	fetched = [];
	vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
		fetched.push({ url: String(input instanceof Request ? input.url : input), init });
		return respond();
	});
}
afterEach(() => vi.restoreAllMocks());

describe("toolEvent", () => {
	it("keeps only the allowlisted filters and the fixed properties", () => {
		const args = { purpose: "SECRET-PURPOSE", query: "SECRET-QUERY", context: "SECRET-CONTEXT", injected: "SECRET-EXTRA", result_count: "SECRET-COUNT",
			slide_type: "chart", industry: "tech", data_type: "trend", impact: "spotlight", style: "minimal", k: 5 };
		const payload = toolEvent("find_references", args, { ms: 12 }, { result_count: 3 }, CLIENT);
		expect(payload.event).toBe("$mcp_tool_call");
		expect(payload.properties).toEqual({
			$mcp_tool_name: "find_references", $mcp_duration_ms: 12, $mcp_is_error: false,
			$mcp_server_name: "eightytwenty", $mcp_server_version: SERVER_VERSION, $mcp_interface: "mcp", $mcp_source: "posthog_mcp_analytics",
			$mcp_client_name: "claude-ai", $mcp_client_version: "0.1.0", $process_person_profile: false, $geoip_disable: true,
			slide_type: "chart", industry: "tech", data_type: "trend", impact: "spotlight", style: "minimal", k: 5, result_count: 3,
		});
		expect(JSON.stringify(payload)).not.toMatch(/SECRET/);
	});

	it("keeps each tool's own filters and skips undefined ones", () => {
		const flows = { purpose: "SECRET", industry: "tech", length: "short", style: undefined, kind: "logo" };
		expect(toolEvent("find_deck_flows", flows, { ms: 1 }, { result_count: 0 }, CLIENT).properties).toMatchObject({ industry: "tech", length: "short", result_count: 0 });
		expect(toolEvent("find_deck_flows", flows, { ms: 1 }, {}, CLIENT).properties).not.toHaveProperty("style");
		expect(toolEvent("find_deck_flows", flows, { ms: 1 }, {}, CLIENT).properties).not.toHaveProperty("kind");
		expect(toolEvent("find_images", { kind: "icon", query: "SECRET", k: 2 }, { ms: 1 }, { result_count: 2 }, CLIENT).properties).toMatchObject({ kind: "icon", k: 2, result_count: 2 });
		expect(toolEvent("get_playbook", { stage: "qa" }, { ms: 0 }, {}, CLIENT).properties).toMatchObject({ stage: "qa" });
		expect(toolEvent("get_playbook", {}, { ms: 0 }, {}, CLIENT).properties).not.toHaveProperty("stage");
		expect(JSON.stringify(toolEvent("find_images", { kind: "icon", query: "SECRET" }, { ms: 1 }, {}, CLIENT))).not.toMatch(/SECRET/);
		expect(JSON.stringify(toolEvent("unknown_tool", { purpose: "SECRET" }, { ms: 1 }, {}, CLIENT))).not.toMatch(/SECRET/);
	});

	it("sends get_reference's id only when the lookup succeeded", () => {
		expect(toolEvent("get_reference", { id: "abc-01" }, { ms: 4 }, {}, CLIENT).properties).toMatchObject({ id: "abc-01" });
		const missing = toolEvent("get_reference", { id: "my-secret-idea" }, { ms: 4, error: "not_found" }, {}, CLIENT);
		expect(missing.properties).toMatchObject({ $mcp_is_error: true, $mcp_error_type: "not_found" });
		expect(JSON.stringify(missing)).not.toMatch(/my-secret-idea/);
	});

	it("sets the error type only on errors", () => {
		expect(toolEvent("find_references", {}, { ms: 1 }, {}, CLIENT).properties).not.toHaveProperty("$mcp_error_type");
		for (const error of ["budget", "not_found", "exception"])
			expect(toolEvent("find_references", {}, { ms: 1, error }, {}, CLIENT).properties).toMatchObject({ $mcp_is_error: true, $mcp_error_type: error });
	});

	it("uses a fresh random distinct_id per call", () => {
		const a = toolEvent("get_playbook", {}, { ms: 0 }, {}, CLIENT).distinct_id;
		const b = toolEvent("get_playbook", {}, { ms: 0 }, {}, CLIENT).distinct_id;
		expect(a).toMatch(UUID);
		expect(b).toMatch(UUID);
		expect(a).not.toBe(b);
	});
});

describe("clientName", () => {
	it("prefers the announced clientInfo", () => {
		expect(clientName({ name: "claude-ai", version: "0.1.0" }, "node")).toEqual({ name: "claude-ai", version: "0.1.0" });
		expect(clientName({ name: "openai-mcp" }, "Claude-User/1.0")).toEqual({ name: "openai-mcp", version: "unknown" });
	});

	it("falls back to the User-Agent's first product token", () => {
		expect(clientName(undefined, "Claude-User/1.0 (+https://support.anthropic.com/)")).toEqual({ name: "Claude-User", version: "1.0" });
		expect(clientName({}, "python-httpx/0.28.1")).toEqual({ name: "python-httpx", version: "0.28.1" });
	});

	it("returns unknown for missing or junk input", () => {
		expect(clientName()).toEqual({ name: "unknown", version: "unknown" });
		expect(clientName(undefined, null)).toEqual({ name: "unknown", version: "unknown" });
		expect(clientName(undefined, "just some words")).toEqual({ name: "unknown", version: "unknown" });
		expect(clientName({ name: "<>!", version: "" })).toEqual({ name: "unknown", version: "unknown" });
	});

	it("sanitises and truncates", () => {
		expect(clientName({ name: "<script>alert(1)</script>", version: "1.0;rm -rf" })).toEqual({ name: "scriptalert1script", version: "1.0" });
		const long = clientName({ name: "a".repeat(200), version: "1".repeat(200) });
		expect(long).toEqual({ name: "a".repeat(32), version: "11111" });
	});

	it("keeps only the numeric prefix of the version", () => {
		for (const [raw, version] of [["1.0.0-beta.1", "1.0.0"], ["v1.2.3", "1.2.3"], ["2025-06-18", "2025"], ["1.0;rm -rf", "1.0"], ["abc", "unknown"], ["1.2.3.4.5", "1.2.3.4"]])
			expect(clientName({ name: "x", version: raw }).version).toBe(version);
		expect(clientName(undefined, "Claude-User/1.0-rc1 (+x)").version).toBe("1.0");
	});
});

describe("send", () => {
	const payload = toolEvent("get_playbook", { stage: "qa" }, { ms: 0 }, {}, CLIENT);

	it("does nothing without a token", async () => {
		spyFetch();
		const ctx = fakeCtx();
		send({} as Env, ctx, { dnt: false }, payload);
		await ctx.settle();
		expect(fetched).toEqual([]);
		expect(ctx.pending).toEqual([]);
	});

	it("does nothing under DNT or GPC", async () => {
		spyFetch();
		const ctx = fakeCtx();
		send({ POSTHOG_PROJECT_TOKEN: "phc_test" } as Env, ctx, { dnt: true }, payload);
		await ctx.settle();
		expect(fetched).toEqual([]);
	});

	it("posts the event to the default host", async () => {
		spyFetch();
		const ctx = fakeCtx();
		send({ POSTHOG_PROJECT_TOKEN: "phc_test" } as Env, ctx, { dnt: false }, payload);
		await ctx.settle();
		expect(fetched.map((f) => f.url)).toEqual(["https://us.i.posthog.com/i/v0/e/"]);
		const { init } = fetched[0];
		expect(init?.method).toBe("POST");
		expect(new Headers(init?.headers).get("content-type")).toBe("application/json");
		expect(init?.signal).toBeInstanceOf(AbortSignal);
		expect(JSON.parse(String(init?.body))).toEqual({ api_key: "phc_test", event: "$mcp_tool_call", distinct_id: payload.distinct_id, properties: payload.properties });
	});

	it("posts to an overridden host", async () => {
		spyFetch();
		const ctx = fakeCtx();
		send({ POSTHOG_PROJECT_TOKEN: "phc_test", POSTHOG_HOST: "https://ph.test" } as Env, ctx, { dnt: false }, payload);
		await ctx.settle();
		expect(fetched.map((f) => f.url)).toEqual(["https://ph.test/i/v0/e/"]);
	});

	it("swallows rejections, error responses, timeouts and bad hosts", async () => {
		const failures = [
			async () => { throw new TypeError("network down"); },
			async () => new Response("boom", { status: 500 }),
			async () => { throw new DOMException("timed out", "TimeoutError"); },
		];
		for (const respond of failures) {
			spyFetch(respond);
			const ctx = fakeCtx();
			expect(() => send({ POSTHOG_PROJECT_TOKEN: "phc_test" } as Env, ctx, { dnt: false }, payload)).not.toThrow();
			await expect(ctx.settle()).resolves.toBeDefined();
			expect(fetched).toHaveLength(1);
			vi.restoreAllMocks();
		}
		const ctx = fakeCtx(); // the real fetch, with a host it cannot parse: no network is reached
		expect(() => send({ POSTHOG_PROJECT_TOKEN: "phc_test", POSTHOG_HOST: "not a url" } as Env, ctx, { dnt: false }, payload)).not.toThrow();
		await expect(ctx.settle()).resolves.toBeDefined();
	});
});

describe("tracked", () => {
	const deps = (ctx: ReturnType<typeof fakeCtx>, meta: { errorType?: string; result_count?: number } = {}) =>
		({ env: { POSTHOG_PROJECT_TOKEN: "phc_test" } as Env, ctx, hints: { dnt: false }, meta, client: () => CLIENT });
	const sent = () => fetched.map((f) => JSON.parse(String(f.init?.body)).properties);

	it("returns the result untouched, forwards (args, ctx) and sends one event", async () => {
		spyFetch();
		const ctx = fakeCtx();
		const result = { content: [{ type: "text" as const, text: "hi" }] };
		const handler = vi.fn(async (_args: { stage?: string }, _extra: { tag: string }) => result);
		const wrapped = tracked("get_playbook", handler, deps(ctx));
		expect(await wrapped({ stage: "qa" }, { tag: "extra" })).toBe(result);
		expect(handler).toHaveBeenCalledWith({ stage: "qa" }, { tag: "extra" });
		await ctx.settle();
		expect(sent()).toEqual([expect.objectContaining({ $mcp_tool_name: "get_playbook", $mcp_is_error: false, stage: "qa", $mcp_client_name: "claude-ai" })]);
		expect(sent()[0].$mcp_duration_ms).toBeGreaterThanOrEqual(0);
	});

	it("records result_count from meta", async () => {
		spyFetch();
		const ctx = fakeCtx();
		const meta: { result_count?: number } = {};
		await tracked("find_images", async (_args: { kind: string; query: string }) => (meta.result_count = 2, { content: [] }), deps(ctx, meta))({ kind: "icon", query: "SECRET" }, {});
		await ctx.settle();
		expect(sent()).toEqual([expect.objectContaining({ kind: "icon", result_count: 2 })]);
		expect(JSON.stringify(sent())).not.toMatch(/SECRET/);
	});

	it("classifies an isError result as not_found", async () => {
		spyFetch();
		const ctx = fakeCtx();
		const result = { content: [], isError: true };
		expect(await tracked("get_reference", async (_args: { id: string }) => result, deps(ctx))({ id: "nope" }, {})).toBe(result);
		await ctx.settle();
		expect(sent()).toEqual([expect.objectContaining({ $mcp_is_error: true, $mcp_error_type: "not_found" })]);
		expect(sent()[0]).not.toHaveProperty("id");
	});

	it("rethrows the original error as exception, or as budget when meta says so", async () => {
		spyFetch();
		for (const [meta, type] of [[{}, "exception"], [{ errorType: "budget" }, "budget"]] as const) {
			const ctx = fakeCtx();
			const error = new Error("daily budget spent");
			await expect(tracked("find_references", async (_args: object) => { throw error; }, deps(ctx, { ...meta }))({}, {})).rejects.toBe(error);
			await ctx.settle();
		}
		expect(sent().map((p) => p.$mcp_error_type)).toEqual(["exception", "budget"]);
	});

	it("never lets a failing event build replace the tool's result or error", async () => {
		spyFetch();
		const ctx = fakeCtx();
		const broken = { ...deps(ctx), client: () => { throw new Error("client failed"); } };
		const result = { content: [] };
		expect(await tracked("get_playbook", async (_args: object) => result, broken)({}, {})).toBe(result);
		const error = new Error("tool failed");
		await expect(tracked("get_playbook", async (_args: object) => { throw error; }, broken)({}, {})).rejects.toBe(error);
		await ctx.settle();
		expect(fetched).toEqual([]);
	});

	it("reads the client lazily, at call time", async () => {
		spyFetch();
		const ctx = fakeCtx();
		let client = { name: "early", version: "0" };
		const wrapped = tracked("get_playbook", async (_args: object) => ({ content: [] }), { ...deps(ctx), client: () => client });
		client = { name: "late", version: "1" };
		await wrapped({}, {});
		await ctx.settle();
		expect(sent()[0]).toMatchObject({ $mcp_client_name: "late", $mcp_client_version: "1" });
	});
});
