import { cloudflareTest, readD1Migrations } from "@cloudflare/vitest-plugin";
import { readdirSync } from "node:fs";
import { defineConfig } from "vitest/config";

const live = !!process.env.LIVE_AI; // LIVE_AI=1 npm test: the live test calls real Workers AI on your wrangler login

export default defineConfig({
	plugins: [
		// wrangler imports these as Text modules (wrangler.jsonc rules); vite needs the same
		{ name: "text-modules", enforce: "pre", transform: (code, id) => (/\.(md|html|svg)$/.test(id) ? `export default ${JSON.stringify(code)};` : undefined) },
		cloudflareTest({
			main: "./src/app.ts", // not src/index.ts: that bundles the gitignored library/ files
			remoteBindings: live,
			wrangler: { configPath: "./wrangler.jsonc" },
			miniflare: { bindings: { TEST_MIGRATIONS: await readD1Migrations("./migrations"), LIVE_AI: live ? "1" : "", PLAYBOOK_FILES: readdirSync("../playbook") } },
		}),
	],
	test: { setupFiles: ["./test/apply-migrations.ts"] },
});
