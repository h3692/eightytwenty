import { env } from "cloudflare:workers";
import { beforeEach, describe, expect, it } from "vitest";
import { DEFAULT_FLAGS, dense, mmr, round, rrf, search } from "../src/search";
import { buffers, fakeAI, floats, library, manifest, near, quantise, rows, seed } from "./fixture";

const lib = library();
const ids = manifest.ids;
const withAI = (ai: ReturnType<typeof fakeAI>) => ({ DB: env.DB, AI: ai as unknown as Ai });

beforeEach(() => seed(env.DB));

describe("rounding and tie-break", () => {
	it("rounds to six decimals", () => {
		expect(round(0.12345678)).toBe(0.123457);
		expect(round(1 / 61)).toBe(0.016393);
	});

	it("breaks score ties by record id", () => {
		// rows 5 and 2 each sit first in one list: equal RRF scores, so the smaller id wins
		expect(rrf([[5], [2]], ids)).toEqual([
			[2, round(1 / 61)],
			[5, round(1 / 61)],
		]);
	});
});

describe("rrf", () => {
	it("sums 1/(60 + rank) over the lists", () => {
		expect(rrf([[0, 1, 2], [2, 0]], ids)).toEqual([
			[0, round(1 / 61 + 1 / 62)],
			[2, round(1 / 63 + 1 / 61)],
			[1, round(1 / 62)],
		]);
	});
});

describe("mmr", () => {
	const cand = (n: number, score: number) => ({ n, id: rows[n].id, deck_id: rows[n].deck_id, score });

	it("keeps at most one slide per deck", () => {
		const out = mmr([cand(0, 0.9), cand(1, 0.8), cand(2, 0.7), cand(3, 0.6)], lib, 5, 1);
		expect(out.map((c) => c.n)).toEqual([0, 2]);
	});

	it("with lambda 1 is pure relevance order", () => {
		const out = mmr([cand(4, 0.2), cand(0, 0.9), cand(2, 0.5)], lib, 3, 1);
		expect(out.map((c) => c.n)).toEqual([0, 2, 4]);
	});

	it("trades relevance for diversity as lambda drops", () => {
		// row 2's vector is a copy of row 0's in this library, so it is redundant once row 0 is picked
		const v = new Int8Array(buffers().vecs);
		v.copyWithin(2 * 1024, 0, 1024);
		const n = new Float32Array(buffers().norms);
		n[2] = n[0];
		const twin = { ...lib, vecs: v, norms: n };
		const cands = [cand(0, 0.9), cand(2, 0.85), cand(4, 0.5)];
		expect(mmr(cands, twin, 2, 1).map((c) => c.n)).toEqual([0, 2]);
		expect(mmr(cands, twin, 2, 0.5).map((c) => c.n)).toEqual([0, 4]);
	});
});

describe("dense", () => {
	it("WASM kernel equals plain JS cosine on the fixture", () => {
		const q = near(3);
		const q8 = quantise(q);
		const qn = Math.hypot(...q8);
		const expected = rows
			.map((r) => {
				const v = quantise(floats[r.n]);
				let dot = 0;
				for (let d = 0; d < 1024; d++) dot += v[d] * q8[d];
				return [r.n, round(dot / (Math.fround(Math.hypot(...v)) * qn))] as [number, number]; // norms.bin is float32
			})
			.sort((a, b) => b[1] - a[1] || (ids[a[0]] < ids[b[0]] ? -1 : 1));
		expect(dense(lib, q, null)).toEqual(expected);
		expect(expected[0][0]).toBe(3);
	});

	it("only scores allowed rows", () => {
		expect(dense(lib, near(3), new Set([1, 7])).map(([n]) => n).sort()).toEqual([1, 7]);
	});
});

describe("library", () => {
	it("refuses a manifest built with a different model", () => {
		expect(() => library({ ...manifest, model: "@cf/baai/bge-large-en-v1.5" })).toThrow(/model/);
	});

	it("refuses vectors that do not match the manifest", () => {
		expect(() => library({ ...manifest, count: 11 })).toThrow(/vecs/);
	});

	it("refuses an embedding with different pooling", async () => {
		const ai = fakeAI(() => near(3), undefined, "mean");
		await expect(search(withAI(ai), lib, { purpose: "market share" })).rejects.toThrow(/pooling/);
	});

	it("refuses records from a different library build", async () => {
		await seed(env.DB, "bge-m3/desc-v1/other");
		await expect(search(withAI(fakeAI(() => near(3))), lib, { purpose: "market share" })).rejects.toThrow(/library_version/);
	});
});

describe("search", () => {
	it("embeds with the pinned model and returns library_version", async () => {
		const ai = fakeAI(() => near(3));
		const out = await search(withAI(ai), lib, { purpose: "  Market   SHARE " , k: 3 });
		expect(out.library_version).toBe(manifest.library_version);
		expect(out.results.length).toBe(3);
		expect(ai.calls[0]).toEqual({ model: "@cf/baai/bge-m3", input: { text: ["market share"] } });
		expect(Object.keys(out.results[0]).sort()).toEqual(["id", "purpose", "score", "slide_type", "why_it_works"]);
	});

	it("rejects bad input", async () => {
		const s = withAI(fakeAI(() => near(3)));
		await expect(search(s, lib, { purpose: "   " })).rejects.toThrow(RangeError);
		await expect(search(s, lib, { purpose: "x", k: 6 })).rejects.toThrow(RangeError);
	});

	it("applies the same filters to the vector and FTS branches", async () => {
		const flags = { ...DEFAULT_FLAGS, cache: false, rerank: false, mmr: false };
		// the query vector is nearest row 3 (a comparison slide) and the words match row 0 (a chart slide)
		const s = withAI(fakeAI(() => near(3)));
		const q = { purpose: "market share of competitors", slide_type: "timeline", industry: "technology", k: 5 };
		const allowed = rows.filter((r) => r.archetype === "timeline" && r.industry === "technology").map((r) => r.id);
		for (const f of [flags, { ...flags, fts: false }]) {
			const out = await search(s, lib, q, f);
			expect(out.results.length).toBe(allowed.length);
			expect(out.results.map((r) => r.id).sort()).toEqual(allowed.sort());
		}
	});

	it("puts a strong text match on top through RRF", async () => {
		const flags = { ...DEFAULT_FLAGS, cache: false, rerank: false, mmr: false };
		const s = withAI(fakeAI(() => near(3)));
		const dense = await search(s, lib, { purpose: "pricing tiers side by side", k: 5 }, { ...flags, fts: false });
		const hybrid = await search(s, lib, { purpose: "pricing tiers side by side", k: 5 }, flags);
		expect(dense.results[0].id).toBe(rows[3].id);
		expect(hybrid.results.map((r) => r.id)).toContain(rows[5].id); // rows 5 and 11 are the pricing slides
		expect(hybrid.results[0].id).not.toBe(dense.results[0].id);
	});

	it("reorders by reranker scores when rerank is on", async () => {
		const flags = { ...DEFAULT_FLAGS, cache: false, mmr: false };
		const ai = fakeAI(() => near(3), (_, texts) => texts.map((t) => (t.includes("team structure") ? 0.99 : 0.01)));
		const out = await search(withAI(ai), lib, { purpose: "market share", k: 2 }, flags);
		expect(out.results[0].id).toBe(rows[4].id); // rows 4 and 10 are the team-structure slides; 4 sorts first
		expect(out.results[0].score).toBe(0.99);
		expect(ai.calls.filter((c) => c.model === "@cf/baai/bge-reranker-base").length).toBe(1);
		expect(ai.calls[1].input.contexts.length).toBeLessThanOrEqual(20);
	});

	it("skips the reranker and FTS when switched off", async () => {
		const ai = fakeAI(() => near(3));
		await search(withAI(ai), lib, { purpose: "market share" }, { ...DEFAULT_FLAGS, fts: false, rerank: false });
		expect(ai.calls.map((c) => c.model)).toEqual(["@cf/baai/bge-m3"]);
	});

	it("returns one slide per deck with MMR on", async () => {
		const out = await search(withAI(fakeAI(() => near(3))), lib, { purpose: "market share", k: 5 }, { ...DEFAULT_FLAGS, cache: false });
		const decks = out.results.map((r) => rows.find((x) => x.id === r.id)!.deck_id);
		expect(new Set(decks).size).toBe(decks.length);
	});

	it("is deterministic: same input twice gives the same output", async () => {
		const flags = { ...DEFAULT_FLAGS, cache: false };
		const s = withAI(fakeAI(() => near(3), (_, t) => t.map((x) => x.length / 100)));
		const a = await search(s, lib, { purpose: "revenue mix", k: 5 }, flags);
		const b = await search(s, lib, { purpose: "revenue mix", k: 5 }, flags);
		expect(b).toEqual(a);
	});

	it("serves identical output from the cache even when the embedding wobbles", async () => {
		let call = 0;
		const ai = fakeAI(() => (call++ === 0 ? near(3) : near(9)));
		const a = await search(withAI(ai), lib, { purpose: "Revenue mix", industry: "retail" });
		const b = await search(withAI(ai), lib, { purpose: "revenue   MIX", industry: "retail" });
		expect(b).toEqual(a);
		expect(ai.calls.filter((c) => c.model === "@cf/baai/bge-m3").length).toBe(1);
		const c = await search(withAI(ai), lib, { purpose: "revenue mix", industry: "technology" });
		expect(c).not.toEqual(a); // other filters, other cache entry
	});

	it("does not store the query text in the cache", async () => {
		await search(withAI(fakeAI(() => near(3))), lib, { purpose: "secret launch plan" });
		const { results } = await env.DB.prepare("SELECT * FROM search_cache").all();
		expect(results.length).toBe(1);
		expect(JSON.stringify(results)).not.toContain("secret");
	});
});
