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
		TEST_MIGRATIONS: import("cloudflare:test").D1Migration[];
		LIVE_AI: string;
		PLAYBOOK_FILES: string[];
	}
}
