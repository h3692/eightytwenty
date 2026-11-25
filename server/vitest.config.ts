import { cloudflareTest, readD1Migrations } from "@cloudflare/vitest-plugin";
import { readdirSync } from "node:fs";
import { defineConfig } from "vitest/config";
import { unstable_readConfig } from "wrangler";

const live = !!process.env.LIVE_AI; // LIVE_AI=1 npm test: the live test calls real Workers AI on your wrangler login
// The resolved deploy config per environment, for the staging test (the workers pool cannot run wrangler itself)
const deployed = (env?: string) => {
	const { name, routes, d1_databases, vars } = unstable_readConfig({ config: "./wrangler.jsonc", env }, { hideWarnings: true });
	return { name, routes, d1_databases, vars };
};

export default defineConfig({
	plugins: [
		// wrangler imports these as Text modules (wrangler.jsonc rules); vite needs the same
		{ name: "text-modules", enforce: "pre", transform: (code, id) => (/\.(md|html|svg)$/.test(id) ? `export default ${JSON.stringify(code)};` : undefined) },
		cloudflareTest({
			main: "./test/worker.ts", // not src/index.ts: that bundles the gitignored library/ files
			remoteBindings: live,
			wrangler: { configPath: "./wrangler.jsonc" },
			miniflare: { bindings: { TEST_MIGRATIONS: await readD1Migrations("./migrations"), TEST_FEEDBACK_MIGRATIONS: await readD1Migrations("./feedback-migrations"), LIVE_AI: live ? "1" : "", PLAYBOOK_FILES: readdirSync("../playbook"), WRANGLER_ENVS: { production: deployed(), staging: deployed("staging") } } },
		}),
	],
	test: { setupFiles: ["./test/apply-migrations.ts"] },
});
