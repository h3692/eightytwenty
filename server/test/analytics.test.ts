import { afterEach, describe, expect, it, vi } from "vitest";
import { clientName, identity, initializeEvent, send, SERVER_VERSION, toolEvent, tracked } from "../src/analytics";

const CLIENT = { name: "claude-ai", version: "0.1.0" };
const WHO = { distinct_id: "day_test", $mcp_user_source: "daily" as const };
const SALTED = { ANALYTICS_SALT: "test-salt" } as Env;
const HEX = /^[0-9a-f]{32}$/;
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
		const payload = toolEvent("find_references", args, { ms: 12 }, { result_count: 3 }, CLIENT, WHO);
		expect(payload.event).toBe("$mcp_tool_call");
		expect(payload.distinct_id).toBe("day_test");
		expect(payload.properties).toEqual({
			$mcp_tool_name: "find_references", $mcp_duration_ms: 12, $mcp_is_error: false,
			$mcp_server_name: "eightytwenty", $mcp_server_version: SERVER_VERSION, $mcp_interface: "mcp", $mcp_source: "posthog_mcp_analytics",
			$mcp_client_name: "claude-ai", $mcp_client_version: "0.1.0", $mcp_user_source: "daily", $process_person_profile: false, $geoip_disable: true,
			slide_type: "chart", industry: "tech", data_type: "trend", impact: "spotlight", style: "minimal", k: 5, result_count: 3,
		});
		expect(JSON.stringify(payload)).not.toMatch(/SECRET/);
	});

	it("keeps each tool's own filters and skips undefined ones", () => {
		const flows = { purpose: "SECRET", industry: "tech", length: "short", style: undefined, kind: "logo" };
		expect(toolEvent("find_deck_flows", flows, { ms: 1 }, { result_count: 0 }, CLIENT, WHO).properties).toMatchObject({ industry: "tech", length: "short", result_count: 0 });
		expect(toolEvent("find_deck_flows", flows, { ms: 1 }, {}, CLIENT, WHO).properties).not.toHaveProperty("style");
		expect(toolEvent("find_deck_flows", flows, { ms: 1 }, {}, CLIENT, WHO).properties).not.toHaveProperty("kind");
		expect(toolEvent("find_images", { kind: "icon", query: "SECRET", k: 2 }, { ms: 1 }, { result_count: 2 }, CLIENT, WHO).properties).toMatchObject({ kind: "icon", k: 2, result_count: 2 });
		expect(toolEvent("get_playbook", { stage: "qa" }, { ms: 0 }, {}, CLIENT, WHO).properties).toMatchObject({ stage: "qa" });
		expect(toolEvent("get_playbook", {}, { ms: 0 }, {}, CLIENT, WHO).properties).not.toHaveProperty("stage");
		expect(JSON.stringify(toolEvent("find_images", { kind: "icon", query: "SECRET" }, { ms: 1 }, {}, CLIENT, WHO))).not.toMatch(/SECRET/);
		expect(JSON.stringify(toolEvent("unknown_tool", { purpose: "SECRET" }, { ms: 1 }, {}, CLIENT, WHO))).not.toMatch(/SECRET/);
	});

	it("sends get_reference's id only when the lookup succeeded", () => {
		expect(toolEvent("get_reference", { id: "abc-01" }, { ms: 4 }, {}, CLIENT, WHO).properties).toMatchObject({ id: "abc-01" });
		const missing = toolEvent("get_reference", { id: "my-secret-idea" }, { ms: 4, error: "not_found" }, {}, CLIENT, WHO);
		expect(missing.properties).toMatchObject({ $mcp_is_error: true, $mcp_error_type: "not_found" });
		expect(JSON.stringify(missing)).not.toMatch(/my-secret-idea/);
	});

	it("sets the error type only on errors", () => {
		expect(toolEvent("find_references", {}, { ms: 1 }, {}, CLIENT, WHO).properties).not.toHaveProperty("$mcp_error_type");
		for (const error of ["budget", "not_found", "exception"])
			expect(toolEvent("find_references", {}, { ms: 1, error }, {}, CLIENT, WHO).properties).toMatchObject({ $mcp_is_error: true, $mcp_error_type: error });
	});

});

describe("initializeEvent", () => {
	it("sends the fixed properties with the cleaned client and protocol version", () => {
		const payload = initializeEvent({ protocolVersion: "2025-06-18", clientInfo: { name: "claude-code", version: "2.1.0 SECRET" } }, "SECRET-UA/9", WHO);
		expect(payload.event).toBe("$mcp_initialize");
		expect(payload.distinct_id).toBe("day_test");
		expect(payload.properties).toEqual({
			$mcp_server_name: "eightytwenty", $mcp_server_version: SERVER_VERSION, $mcp_interface: "mcp", $mcp_source: "posthog_mcp_analytics",
			$mcp_client_name: "claude-code", $mcp_client_version: "2.1.0", $mcp_protocol_version: "2025-06-18", $mcp_user_source: "daily",
			$process_person_profile: false, $geoip_disable: true,
		});
		expect(JSON.stringify(payload)).not.toMatch(/SECRET/);
	});

	it("cleans a junk protocol version and falls back to the User-Agent and unknown", () => {
		expect(initializeEvent({ protocolVersion: "x<script>" }, null, WHO).properties.$mcp_protocol_version).toBe("xscript");
		expect(initializeEvent({ protocolVersion: "<>!" }, null, WHO).properties.$mcp_protocol_version).toBe("unknown");
		expect(initializeEvent({ protocolVersion: "1".repeat(200) }, null, WHO).properties.$mcp_protocol_version).toBe("1".repeat(32));
		expect(initializeEvent(undefined, "python-httpx/0.28.1", WHO).properties).toMatchObject({ $mcp_client_name: "python-httpx", $mcp_client_version: "0.28.1", $mcp_protocol_version: "unknown" });
	});

	it("carries the conversation hash with the identity", () => {
		expect(initializeEvent({}, null, { ...WHO, mcp_conversation: "abc" }).properties).toMatchObject({ mcp_conversation: "abc" });
	});
});

describe("identity", () => {
	const SUBJECT = { "openai/subject": "SECRET-SUBJECT-1", "openai/session": "SECRET-SESSION-1" };

	it("hashes ChatGPT's subject into a stable usr_ id and its session into mcp_conversation", async () => {
		const a = await identity(SALTED, "203.0.113.9", SUBJECT);
		expect(a.distinct_id).toMatch(/^usr_[0-9a-f]{32}$/);
		expect(a.$mcp_user_source).toBe("chatgpt");
		expect(a.mcp_conversation).toMatch(HEX);
		expect(await identity(SALTED, "198.51.100.7", SUBJECT)).toEqual(a); // the subject wins over the address
		const other = await identity(SALTED, "203.0.113.9", { "openai/subject": "SECRET-SUBJECT-2", "openai/session": "SECRET-SESSION-2" });
		expect(other.distinct_id).not.toBe(a.distinct_id);
		expect(other.mcp_conversation).not.toBe(a.mcp_conversation);
		expect((await identity({ ANALYTICS_SALT: "other-salt" } as Env, "203.0.113.9", SUBJECT)).distinct_id).not.toBe(a.distinct_id);
	});

	it("never puts the raw subject, session, address or key in the result", async () => {
		for (const meta of [SUBJECT, { "openai/session": "SECRET-SESSION-1" }, {}])
			expect(JSON.stringify(await identity(SALTED, "203.0.113.9", meta))).not.toMatch(/SECRET|203\.0\.113|test-salt/);
		expect(JSON.stringify(await identity(SALTED, "2001:db8:1:2::/64", {}))).not.toMatch(/2001|db8/);
	});

	it("gives direct apps a day_ id per address, stable within the UTC day and new the next day", async () => {
		try {
			vi.setSystemTime(new Date("2026-11-21T00:00:01Z"));
			const a = await identity(SALTED, "203.0.113.9");
			expect(a).toEqual({ distinct_id: expect.stringMatching(/^day_[0-9a-f]{32}$/), $mcp_user_source: "daily" });
			vi.setSystemTime(new Date("2026-11-21T23:59:59Z"));
			expect(await identity(SALTED, "203.0.113.9", {})).toEqual(a);
			expect((await identity(SALTED, "198.51.100.7")).distinct_id).not.toBe(a.distinct_id);
			vi.setSystemTime(new Date("2026-11-22T00:00:01Z"));
			expect((await identity(SALTED, "203.0.113.9")).distinct_id).not.toBe(a.distinct_id);
		} finally {
			vi.useRealTimers();
		}
	});

	it("keeps a fresh random id for claude.ai, a missing address or a missing salt", async () => {
		const ids = [await identity(SALTED, "anthropic"), await identity(SALTED, "unknown"), await identity({} as Env, "203.0.113.9", SUBJECT), await identity({} as Env, "anthropic", SUBJECT)];
		for (const who of ids) expect(who).toEqual({ distinct_id: expect.stringMatching(UUID), $mcp_user_source: "none" });
		expect(new Set(ids.map((w) => w.distinct_id)).size).toBe(ids.length);
		expect((await identity(SALTED, "anthropic", { "openai/session": "s" })).mcp_conversation).toMatch(HEX);
	});

	it("ignores a subject or session that is not a non-empty string", async () => {
		const who = await identity(SALTED, "anthropic", { "openai/subject": "", "openai/session": 42 });
		expect(who).toEqual({ distinct_id: expect.stringMatching(UUID), $mcp_user_source: "none" });
	});

	it("ignores a subject or session over 256 characters", async () => {
		const who = await identity(SALTED, "anthropic", { "openai/subject": "s".repeat(257), "openai/session": "s".repeat(257) });
		expect(who).toEqual({ distinct_id: expect.stringMatching(UUID), $mcp_user_source: "none" });
		expect((await identity(SALTED, "anthropic", { "openai/subject": "s".repeat(256) })).$mcp_user_source).toBe("chatgpt");
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
	const payload = toolEvent("get_playbook", { stage: "qa" }, { ms: 0 }, {}, CLIENT, WHO);

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
		({ env: { POSTHOG_PROJECT_TOKEN: "phc_test", ANALYTICS_SALT: "test-salt" } as Env, ctx, hints: { dnt: false }, meta, client: () => CLIENT, key: "203.0.113.9" });
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

	it("identifies the caller from the tool's ctx._meta and the client key, never sending the raw values", async () => {
		spyFetch();
		const ctx = fakeCtx();
		const handler = async (_args: object, _extra: object) => ({ content: [] });
		await tracked("get_playbook", handler, deps(ctx))({}, { mcpReq: { _meta: { "openai/subject": "SECRET-SUBJECT", "openai/session": "SECRET-SESSION" } } });
		await ctx.settle(); // one at a time: the hashing is async, so events could otherwise arrive out of order
		await tracked("get_playbook", handler, deps(ctx))({}, {});
		await ctx.settle();
		await tracked("get_playbook", handler, { ...deps(ctx), key: "anthropic" })({}, {});
		await ctx.settle();
		const events = fetched.map((f) => JSON.parse(String(f.init?.body)));
		expect(events.map((e) => [e.distinct_id.slice(0, 4), e.properties.$mcp_user_source])).toEqual([["usr_", "chatgpt"], ["day_", "daily"], [expect.any(String), "none"]]);
		expect(events[0].properties.mcp_conversation).toMatch(HEX);
		expect(events[2].distinct_id).toMatch(UUID);
		expect(JSON.stringify(events)).not.toMatch(/SECRET|203\.0\.113|test-salt/);
	});
});
