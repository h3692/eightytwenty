// Search core: bge-m3 query embedding -> exact int8 brute force (WASM SIMD) + D1 FTS5 BM25 with the same filters
// -> RRF -> bge-reranker-base -> MMR (max 1 per deck). Scores are rounded and ties broken by record id, and results are
// cached in D1 per (normalised query, library_version), so an identical query always returns identical results.
export const EMBED_MODEL = "@cf/baai/bge-m3";
export const RERANK_MODEL = "@cf/baai/bge-reranker-base";
export const DIMS = 1024; // dot.wat hard-codes 1024-d rows
const POOL = 50, RERANK_POOL = 20, RRF_K = 60, MAX_K = 5, MAX_PURPOSE = 1000, MAX_TERMS = 32;

export type Manifest = { library_version: string; model: string; pooling: string; dims: number; count: number; ids: string[] };
export type Library = { manifest: Manifest; vecs: Int8Array; norms: Float32Array; scan: (q8: Int8Array) => Int32Array };
export type Query = { purpose: string; slide_type?: string; industry?: string; data_type?: string; k?: number };
// Stage switches for the S6 ablation: dense only -> +fts (RRF) -> +rerank -> +mmr.
export type Flags = { fts: boolean; rerank: boolean; mmr: boolean; cache: boolean; lambda: number };
export type Result = { id: string; slide_type: string; purpose: string; why_it_works: string; score: number };
type Row = { n: number; id: string; deck_id: string; archetype: string; purpose: string; why_it_works: string; description: string };

export const DEFAULT_FLAGS: Flags = { fts: true, rerank: true, mmr: true, cache: true, lambda: 0.7 };

export const round = (x: number) => Math.round(x * 1e6) / 1e6;
const byScore = (ids: string[]) => (a: [number, number], b: [number, number]) =>
	b[1] - a[1] || (ids[a[0]] < ids[b[0]] ? -1 : ids[a[0]] > ids[b[0]] ? 1 : 0);

export function loadLibrary(dot: WebAssembly.Module, vecs: ArrayBuffer, norms: ArrayBuffer, manifest: Manifest): Library {
	const { model, pooling, dims, count, ids } = manifest;
	if (model !== EMBED_MODEL || pooling !== "cls" || dims !== DIMS)
		throw new Error(`Library model is ${model} (${pooling}, ${dims}-d) but queries are embedded with ${EMBED_MODEL} (cls, ${DIMS}-d): re-embed the library.`);
	if (vecs.byteLength !== count * DIMS || norms.byteLength !== count * 4 || ids.length !== count)
		throw new Error(`library/vecs.bin, norms.bin and manifest.json disagree on the row count (${count}): re-run embed.`);
	const ex = new WebAssembly.Instance(dot).exports as { mem: WebAssembly.Memory; scan: (v: number, q: number, o: number, n: number) => void };
	const q = count * DIMS, out = q + DIMS; // wasm memory layout: vectors | query | int32 dot products
	ex.mem.grow(Math.ceil((out + count * 4) / 65536));
	new Int8Array(ex.mem.buffer).set(new Int8Array(vecs));
	return {
		manifest,
		vecs: new Int8Array(ex.mem.buffer, 0, q),
		norms: new Float32Array(norms),
		scan(q8) {
			new Int8Array(ex.mem.buffer, q, DIMS).set(q8);
			ex.scan(0, q, out, count);
			return new Int32Array(ex.mem.buffer, out, count);
		},
	};
}

// Cosine of the query against every allowed row (same int8 quantisation as pipeline/embed.py), top POOL.
export function dense(lib: Library, embedding: number[], allowed: Set<number> | null): [number, number][] {
	const m = Math.max(...embedding.map(Math.abs)) || 1;
	const q8 = Int8Array.from(embedding, (x) => Math.round((x * 127) / m));
	const qn = Math.hypot(...q8) || 1;
	const dots = lib.scan(q8);
	const score = new Float64Array(dots.length).fill(-Infinity);
	for (let n = 0; n < dots.length; n++) if (!allowed || allowed.has(n)) score[n] = round(dots[n] / ((lib.norms[n] || 1) * qn));
	// Sort only the rows scoring at least the POOL-th best (ties included): same top POOL as a full sort, far less work.
	const cut = Math.max(score.slice().sort()[dots.length - POOL] ?? -Infinity, -Number.MAX_VALUE);
	const hits: [number, number][] = [];
	for (let n = 0; n < dots.length; n++) if (score[n] >= cut) hits.push([n, score[n]]);
	return hits.sort(byScore(lib.manifest.ids)).slice(0, POOL);
}

// Reciprocal rank fusion: score = sum over lists of 1 / (60 + rank).
export function rrf(lists: number[][], ids: string[]): [number, number][] {
	const s = new Map<number, number>();
	for (const list of lists) list.forEach((n, i) => s.set(n, (s.get(n) ?? 0) + 1 / (RRF_K + i + 1)));
	return [...s].map(([n, x]): [number, number] => [n, round(x)]).sort(byScore(ids));
}

// Greedy MMR over min-max normalised relevance and int8 cosine between slides, at most one slide per deck.
export function mmr<C extends { n: number; id: string; deck_id: string; score: number }>(cands: C[], lib: Library, k: number, lambda: number): C[] {
	const lo = Math.min(...cands.map((c) => c.score)), hi = Math.max(...cands.map((c) => c.score));
	const rel = (c: C) => (hi > lo ? (c.score - lo) / (hi - lo) : 1);
	const sim = (a: number, b: number) => {
		let dot = 0;
		for (let d = 0; d < DIMS; d++) dot += lib.vecs[a * DIMS + d] * lib.vecs[b * DIMS + d];
		return dot / ((lib.norms[a] || 1) * (lib.norms[b] || 1));
	};
	const picked: C[] = [];
	const maxSim = new Map<C, number>(); // max cosine to the picked slides, updated once per pick instead of recomputed
	let left = cands;
	while (picked.length < k && (left = left.filter((c) => !picked.some((p) => p.deck_id === c.deck_id))).length) {
		let best = left[0], bestScore = -Infinity;
		for (const c of left) {
			const v = round(lambda * rel(c) - (1 - lambda) * (maxSim.get(c) ?? 0));
			if (v > bestScore || (v === bestScore && c.id < best.id)) [best, bestScore] = [c, v];
		}
		picked.push(best);
		for (const c of left) if (c.deck_id !== best.deck_id) maxSim.set(c, Math.max(maxSim.get(c) ?? -Infinity, sim(c.n, best.n)));
	}
	return picked;
}

export async function search(env: Pick<Env, "DB" | "AI">, lib: Library, query: Query, flags: Flags = DEFAULT_FLAGS): Promise<{ results: Result[]; library_version: string }> {
	const { library_version, ids } = lib.manifest;
	const purpose = (query.purpose ?? "").normalize("NFKC").toLowerCase().replace(/\s+/g, " ").trim();
	const k = query.k ?? MAX_K;
	if (!purpose || purpose.length > MAX_PURPOSE) throw new RangeError(`purpose must be 1 to ${MAX_PURPOSE} characters.`);
	if (!Number.isInteger(k) || k < 1 || k > MAX_K) throw new RangeError(`k must be a whole number from 1 to ${MAX_K}.`);
	const filters = ([["archetype", query.slide_type], ["industry", query.industry], ["data_type", query.data_type]] as const).filter(([, v]) => v != null);

	let key = "";
	if (flags.cache) {
		// hashed, so the query text is never stored
		const id = [library_version, purpose, query.slide_type ?? null, query.industry ?? null, query.data_type ?? null, k, flags.fts, flags.rerank, flags.mmr, flags.lambda];
		const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(id)));
		key = [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
		const hit = await env.DB.prepare("SELECT results FROM search_cache WHERE key = ?").bind(key).first<string>("results");
		if (hit) return { results: JSON.parse(hit), library_version };
	}

	// One D1 round trip, in parallel with the embedding: build check, filter set for the vector branch, FTS branch.
	const where = filters.map(([col]) => ` AND s.${col} = ?`).join(""), args = filters.map(([, v]) => v);
	const terms = [...new Set(purpose.match(/[\p{L}\p{N}]+/gu) ?? [])].slice(0, MAX_TERMS);
	const fts = flags.fts && terms.length > 0;
	const stmts = [env.DB.prepare("SELECT value FROM meta WHERE key = 'library_version'")];
	if (filters.length) stmts.push(env.DB.prepare(`SELECT s.n FROM slides s WHERE 1 = 1${where}`).bind(...args));
	if (fts)
		stmts.push(env.DB.prepare(`SELECT s.n FROM slides_fts JOIN slides s ON s.n = slides_fts.rowid WHERE slides_fts MATCH ?${where}
			ORDER BY bm25(slides_fts), s.id LIMIT ${POOL}`).bind(terms.map((t) => `"${t}"`).join(" OR "), ...args));
	const [emb, batch] = await Promise.all([
		env.AI.run(EMBED_MODEL, { text: [purpose] }) as Promise<{ data?: number[][]; pooling?: string }>,
		env.DB.batch<Record<string, any>>(stmts),
	]);
	const version = batch[0].results[0]?.value;
	if (version !== library_version)
		throw new Error(`D1 holds library_version ${version} but the bundled vectors are ${library_version}: load the matching records.sql.`);
	if (emb.pooling !== lib.manifest.pooling || emb.data?.[0]?.length !== DIMS)
		throw new Error(`${EMBED_MODEL} returned pooling ${emb.pooling}, ${emb.data?.[0]?.length}-d; the library was embedded with ${lib.manifest.pooling}, ${DIMS}-d.`);

	const vec = dense(lib, emb.data[0], filters.length ? new Set(batch[1].results.map((r) => r.n as number)) : null);
	const pool = (flags.fts ? rrf([vec.map(([n]) => n), fts ? batch[batch.length - 1].results.map((r) => r.n as number) : []], ids) : vec).slice(0, RERANK_POOL);

	let results: Result[] = [];
	if (pool.length) {
		const { results: found } = await env.DB.prepare(`SELECT n, id, deck_id, archetype, purpose, why_it_works, description FROM slides WHERE n IN (${pool.map(() => "?").join(", ")})`)
			.bind(...pool.map(([n]) => n)).all<Row>();
		const byN = new Map(found.map((r) => [r.n, r]));
		const cands = pool.map(([n, score]) => ({ ...byN.get(n)!, score }));
		if (flags.rerank) {
			// workers-types (5.20261104.1) leaves `query` out of the reranker input type, hence the cast
			const r = (await (env.AI as any).run(RERANK_MODEL, { query: purpose, contexts: cands.map((c) => ({ text: c.description })), top_k: cands.length })) as { response: { id: number; score: number }[] };
			for (const { id: i, score } of r.response) cands[i].score = round(score);
			cands.sort((a, b) => b.score - a.score || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
		}
		const picked = flags.mmr ? mmr(cands, lib, k, flags.lambda) : cands.slice(0, k);
		results = picked.map((c) => ({ id: c.id, slide_type: c.archetype, purpose: c.purpose, why_it_works: c.why_it_works, score: c.score }));
	}

	if (key) {
		const { meta } = await env.DB.prepare("INSERT OR IGNORE INTO search_cache (key, results, library_version) VALUES (?, ?, ?)").bind(key, JSON.stringify(results), library_version).run();
		if (!meta.changes) {
			// an identical query stored its result first: serve that one, so both callers see the same output
			const stored = await env.DB.prepare("SELECT results FROM search_cache WHERE key = ?").bind(key).first<string>("results");
			if (stored) return { results: JSON.parse(stored), library_version };
		}
	}
	return { results, library_version };
}
