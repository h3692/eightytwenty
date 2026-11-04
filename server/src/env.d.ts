declare module "*.wasm" { const m: WebAssembly.Module; export default m; }
declare module "*.bin" { const data: ArrayBuffer; export default data; }

interface Env {
	DB: D1Database;
	AI: Ai;
}

declare namespace Cloudflare {
	interface Env {
		DB: D1Database;
		AI: Ai;
		TEST_MIGRATIONS: import("cloudflare:test").D1Migration[];
		LIVE_AI: string;
	}
}
