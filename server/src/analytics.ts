// Usage statistics: one $mcp_tool_call event per tool call and one $mcp_initialize per initialize, sent to PostHog only when POSTHOG_PROJECT_TOKEN is
// set and the request carries no DNT/GPC. Only allowlisted enum and number filters are sent: never free text, results or
// error text. The caller is identified only by keyed one-way hashes (ANALYTICS_SALT): ChatGPT's user and conversation ids,
// else the client key (IP, IPv6 /64) with the UTC date, so direct apps get a new id daily. Never the raw ids or address.
export const SERVER_VERSION = "1.0.0";

type Meta = { errorType?: string; result_count?: number };
type Client = { name: string; version: string };
type Who = { distinct_id: string; $mcp_user_source: "chatgpt" | "daily" | "none"; mcp_conversation?: string };
type Payload = ReturnType<typeof toolEvent> | ReturnType<typeof initializeEvent>;
type Deps = { env: Env; ctx: { waitUntil(p: Promise<unknown>): void }; hints: { dnt: boolean }; meta: Meta; client: () => Client; key: string };

// Each tool's filters the zod schemas constrain to enums or numbers, plus its result count.
const ALLOW: Record<string, string[]> = {
	find_references: ["slide_type", "industry", "data_type", "impact", "style", "k", "result_count"],
	find_deck_flows: ["industry", "length", "style", "result_count"],
	find_images: ["kind", "k", "result_count"],
	get_playbook: ["stage"],
	get_reference: ["id"],
};

export function toolEvent(name: string, args: Record<string, unknown>, outcome: { ms: number; error?: string }, meta: Meta, client: Client, who: Who) {
	const filters: Record<string, unknown> = {};
	for (const key of ALLOW[name] ?? []) {
		const value = key === "result_count" ? meta.result_count : args[key];
		if (value !== undefined) filters[key] = value;
	}
	if (outcome.error) delete filters.id; // get_reference accepts any id, so one that was not found may be user text
	const { distinct_id, ...user } = who;
	return {
		event: "$mcp_tool_call",
		distinct_id,
		properties: {
			$mcp_tool_name: name,
			$mcp_duration_ms: outcome.ms,
			$mcp_is_error: !!outcome.error,
			...(outcome.error ? { $mcp_error_type: outcome.error } : {}),
			$mcp_server_name: "eightytwenty",
			$mcp_server_version: SERVER_VERSION,
			$mcp_interface: "mcp",
			$mcp_source: "posthog_mcp_analytics",
			$mcp_client_name: client.name,
			$mcp_client_version: client.version,
			...user,
			$process_person_profile: false,
			$geoip_disable: true,
			...filters,
		},
	};
}

const clean = (s?: string) => s?.replace(/[^\w.\-]/g, "").slice(0, 32) || "unknown";
// Only the numeric prefix of the raw version (1.0.0-beta.1 -> 1.0.0), so no free text gets through.
const numeric = (s?: string) => s?.match(/^v?(\d{1,5}(?:\.\d{1,5}){0,3})/)?.[1] ?? "unknown";

// The AI app's announced clientInfo, else the first name/version product token of its User-Agent.
export function clientName(info?: { name?: string; version?: string }, userAgent?: string | null): Client {
	if (info?.name) return { name: clean(info.name), version: numeric(info.version) };
	const [, name, version] = userAgent?.match(/^\s*([^\s/]+)\/(\S+)/) ?? [];
	return { name: clean(name), version: numeric(version) };
}

// One $mcp_initialize per initialize request ("client connects"): the announced client and protocol version, cleaned.
export function initializeEvent(params: { protocolVersion?: string; clientInfo?: { name?: string; version?: string } } | undefined, userAgent: string | null | undefined, who: Who) {
	const client = clientName(params?.clientInfo, userAgent);
	const { distinct_id, ...user } = who;
	return {
		event: "$mcp_initialize",
		distinct_id,
		properties: {
			$mcp_server_name: "eightytwenty",
			$mcp_server_version: SERVER_VERSION,
			$mcp_interface: "mcp",
			$mcp_source: "posthog_mcp_analytics",
			$mcp_client_name: client.name,
			$mcp_client_version: client.version,
			$mcp_protocol_version: clean(params?.protocolVersion),
			...user,
			$process_person_profile: false,
			$geoip_disable: true,
		},
	};
}

// ChatGPT's openai/subject (a user) wins, then the client key with the UTC date (direct apps). claude.ai shares Anthropic's
// egress IPs, so it (and a missing IP or salt) keeps a fresh random id per call. h() = HMAC-SHA256 with the salt, 32 hex.
export async function identity(env: Env, key: string, meta?: Record<string, unknown>): Promise<Who> {
	const random: Who = { distinct_id: crypto.randomUUID(), $mcp_user_source: "none" };
	if (!env.ANALYTICS_SALT) return random;
	const hmac = await crypto.subtle.importKey("raw", new TextEncoder().encode(env.ANALYTICS_SALT), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
	const h = async (x: string) => [...new Uint8Array(await crypto.subtle.sign("HMAC", hmac, new TextEncoder().encode(x)))]
		.slice(0, 16).map((b) => b.toString(16).padStart(2, "0")).join("");
	// non-empty strings up to 256 characters only, so a huge value is never hashed
	const ok = (v: unknown): v is string => typeof v === "string" && v.length > 0 && v.length <= 256;
	const subject = meta?.["openai/subject"], session = meta?.["openai/session"];
	const conversation = ok(session) ? { mcp_conversation: await h(`session|${session}`) } : {};
	if (ok(subject)) return { distinct_id: `usr_${await h(`subject|${subject}`)}`, $mcp_user_source: "chatgpt", ...conversation };
	if (key !== "anthropic" && key !== "unknown")
		return { distinct_id: `day_${await h(`day|${new Date().toISOString().slice(0, 10)}|${key}`)}`, $mcp_user_source: "daily", ...conversation };
	return { ...random, ...conversation };
}

// Fire and forget: the delivery never delays, changes or fails the tool response.
export function send(env: Env, ctx: Deps["ctx"], hints: Deps["hints"], payload: Payload): void {
	if (!env.POSTHOG_PROJECT_TOKEN || hints.dnt) return;
	ctx.waitUntil(fetch(`${env.POSTHOG_HOST ?? "https://us.i.posthog.com"}/i/v0/e/`, {
		method: "POST",
		headers: { "content-type": "application/json" },
		body: JSON.stringify({ api_key: env.POSTHOG_PROJECT_TOKEN, ...payload }),
		signal: AbortSignal.timeout(3000),
	}).catch(() => {}));
}

// Wraps one tool callback: times it, classifies the outcome, sends the event, and returns or rethrows unchanged.
export function tracked<A extends Record<string, unknown>, C, R extends object>(name: string, handler: (args: A, ctx: C) => Promise<R>, deps: Deps) {
	return async (args: A, ctx: C): Promise<R> => {
		const start = Date.now(); // Workers' clock advances only on I/O, so this is I/O time: CPU-only tools read 0
		let error: string | undefined;
		try {
			const result = await handler(args, ctx);
			if ((result as { isError?: boolean }).isError) error = "not_found";
			return result;
		} catch (e) {
			error = deps.meta.errorType ?? "exception";
			throw e;
		} finally {
			try {
				const ms = Date.now() - start, client = deps.client(), meta = (ctx as { mcpReq?: { _meta?: Record<string, unknown> } } | undefined)?.mcpReq?._meta;
				// The hashing is async: it runs after the response, like the delivery.
				deps.ctx.waitUntil(identity(deps.env, deps.key, meta).then((who) => send(deps.env, deps.ctx, deps.hints, toolEvent(name, args, { ms, error }, deps.meta, client, who))).catch(() => {}));
			} catch {} // analytics never replaces the tool's result or error
		}
	};
}
