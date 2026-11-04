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
	LIMIT_PER_MINUTE: number;
	LIMIT_PER_MINUTE_SHARED: number;
	DAILY_SEARCH_BUDGET: number;
}

declare namespace Cloudflare {
	interface Env {
		DB: D1Database;
		AI: Ai;
		ASSETS: Fetcher;
		LIMITER: DurableObjectNamespace<import("./limiter").Limiter>;
		LIMIT_PER_MINUTE: number;
		LIMIT_PER_MINUTE_SHARED: number;
		DAILY_SEARCH_BUDGET: number;
		TEST_MIGRATIONS: import("cloudflare:test").D1Migration[];
		LIVE_AI: string;
		PLAYBOOK_FILES: string[];
	}
}
