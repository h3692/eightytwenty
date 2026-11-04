// LIVE_AI=1 npm test: real bge-m3 + bge-reranker-base on your wrangler login, against the synthetic fixture library.
import { env } from "cloudflare:workers";
import { expect, it } from "vitest";
import { DEFAULT_FLAGS, search } from "../src/search";
import { library, manifest, seed } from "./fixture";

it.skipIf(!env.LIVE_AI)("runs every stage on Workers AI and repeats identically", async () => {
	await seed(env.DB);
	const lib = library();
	const q = { purpose: "show how market share of competitors changed", k: 3 };
	const a = await search(env, lib, q, { ...DEFAULT_FLAGS, cache: false });
	const b = await search(env, lib, q, { ...DEFAULT_FLAGS, cache: false });
	expect(a.library_version).toBe(manifest.library_version);
	expect(a.results.length).toBe(3);
	expect(b).toEqual(a);
});
