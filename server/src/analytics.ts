// Anonymous usage statistics: one $mcp_tool_call event per tool call, sent to PostHog only when POSTHOG_PROJECT_TOKEN is
// set and the request carries no DNT/GPC. Only allowlisted enum and number filters are sent: never free text, results,
// error text or anything derived from the IP.
export const SERVER_VERSION = "1.0.0";

type Meta = { errorType?: string; result_count?: number };
type Client = { name: string; version: string };
type Payload = ReturnType<typeof toolEvent>;
type Deps = { env: Env; ctx: { waitUntil(p: Promise<unknown>): void }; hints: { dnt: boolean }; meta: Meta; client: () => Client };

// Each tool's filters the zod schemas constrain to enums or numbers, plus its result count.
const ALLOW: Record<string, string[]> = {
	find_references: ["slide_type", "industry", "data_type", "impact", "style", "k", "result_count"],
	find_deck_flows: ["industry", "length", "style", "result_count"],
	find_images: ["kind", "k", "result_count"],
	get_playbook: ["stage"],
	get_reference: ["id"],
};

export function toolEvent(name: string, args: Record<string, unknown>, outcome: { ms: number; error?: string }, meta: Meta, client: Client) {
	const filters: Record<string, unknown> = {};
	for (const key of ALLOW[name] ?? []) {
		const value = key === "result_count" ? meta.result_count : args[key];
		if (value !== undefined) filters[key] = value;
	}
	if (outcome.error) delete filters.id; // get_reference accepts any id, so one that was not found may be user text
	return {
		event: "$mcp_tool_call",
		distinct_id: crypto.randomUUID(), // a new anonymous id per call: calls are not linked
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
				send(deps.env, deps.ctx, deps.hints, toolEvent(name, args, { ms: Date.now() - start, error }, deps.meta, deps.client()));
			} catch {} // analytics never replaces the tool's result or error
		}
	};
}
