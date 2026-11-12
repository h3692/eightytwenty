declare module "*.wasm" { const m: WebAssembly.Module; export default m; }
declare module "*.bin" { const data: ArrayBuffer; export default data; }
declare module "*.md" { const text: string; export default text; }
declare module "*.html" { const text: string; export default text; }
declare module "*.svg" { const text: string; export default text; }

interface Env {
	DB: D1Database;
	AI: Ai;
	ASSETS: Fetcher;
	LIMITER: DurableObjectNamespace<import("./limiter").Limiter>;
	SEARCHER: DurableObjectNamespace<import("./app").Searcher>;
	LIMIT_PER_MINUTE: number;
	LIMIT_PER_MINUTE_SHARED: number;
	DAILY_SEARCH_BUDGET: number;
	DAILY_PHOTO_BUDGET: number;
	OPENVERSE_CLIENT_ID?: string; // secrets (wrangler secret put); photos fall back to anonymous Openverse calls without them
	OPENVERSE_CLIENT_SECRET?: string;
	OPENAI_APPS_CHALLENGE?: string; // secret: ChatGPT's domain verification token, served at /.well-known/openai-apps-challenge
	GLAMA_CLAIM?: string; // secret: the Glama connector claim JSON, served at /.well-known/glama.json
	POSTHOG_PROJECT_TOKEN?: string; // secret (wrangler secret put): usage statistics are sent to PostHog only when it is set
	POSTHOG_HOST?: string;
}

declare namespace Cloudflare {
	interface Env {
		DB: D1Database;
		AI: Ai;
		ASSETS: Fetcher;
		LIMITER: DurableObjectNamespace<import("./limiter").Limiter>;
		SEARCHER: DurableObjectNamespace<import("./app").Searcher>;
		LIMIT_PER_MINUTE: number;
		LIMIT_PER_MINUTE_SHARED: number;
		DAILY_SEARCH_BUDGET: number;
		DAILY_PHOTO_BUDGET: number;
		OPENVERSE_CLIENT_ID?: string;
		OPENVERSE_CLIENT_SECRET?: string;
		OPENAI_APPS_CHALLENGE?: string;
		POSTHOG_PROJECT_TOKEN?: string;
		POSTHOG_HOST?: string;
		TEST_MIGRATIONS: import("cloudflare:test").D1Migration[];
		LIVE_AI: string;
		PLAYBOOK_FILES: string[];
	}
}
