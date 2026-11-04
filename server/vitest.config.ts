import { cloudflareTest, readD1Migrations } from "@cloudflare/vitest-plugin";
import { defineConfig } from "vitest/config";

const live = !!process.env.LIVE_AI; // LIVE_AI=1 npm test: the live test calls real Workers AI on your wrangler login

export default defineConfig({
	plugins: [
		cloudflareTest({
			main: "./src/search.ts", // not src/index.ts: that bundles the gitignored library/ files
			remoteBindings: live,
			wrangler: { configPath: "./wrangler.jsonc" },
			miniflare: { bindings: { TEST_MIGRATIONS: await readD1Migrations("./migrations"), LIVE_AI: live ? "1" : "" } },
		}),
	],
	test: { setupFiles: ["./test/apply-migrations.ts"] },
});
