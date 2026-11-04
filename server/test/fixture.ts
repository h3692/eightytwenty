// Small synthetic library in the layout the pipeline writes (pipeline/embed.py + pipeline/package.py).
import dot from "../src/dot.wasm";
import { DIMS, loadLibrary, type Manifest } from "../src/search";

// Same tables as pipeline/package.py SCHEMA_SQL (the fixture must stay in step with it).
const SCHEMA = [
	"DROP TABLE IF EXISTS slides_fts",
	"DROP TABLE IF EXISTS slides",
	"DROP TABLE IF EXISTS meta",
	`CREATE TABLE slides (n INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, deck_id TEXT NOT NULL, archetype TEXT NOT NULL,
  industry TEXT NOT NULL, data_type TEXT NOT NULL, purpose TEXT NOT NULL, why_it_works TEXT NOT NULL,
  description TEXT NOT NULL, dna TEXT NOT NULL)`,
	"CREATE INDEX slides_filters ON slides (archetype, industry, data_type)",
	"CREATE VIRTUAL TABLE slides_fts USING fts5(purpose, why_it_works, description, tokenize='porter')",
	"CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
];

const TOPICS = [
	"market share of competitors over time",
	"product roadmap with quarterly milestones",
	"revenue mix by business segment",
	"customer journey pain points",
	"team structure and reporting lines",
	"pricing tiers side by side",
];
const ARCHETYPES = ["chart", "timeline", "comparison"];
const INDUSTRIES = ["retail", "technology"];

export type Row = { n: number; id: string; deck_id: string; archetype: string; industry: string; data_type: string; purpose: string; why_it_works: string; description: string };

function rng(seed: number) {
	return () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648) * 2 - 1;
}

export const quantise = (v: number[]) => {
	const m = Math.max(...v.map(Math.abs)) || 1;
	return Int8Array.from(v, (x) => Math.round((x * 127) / m));
};

// 12 rows: 6 decks x 2 slides; row n's float vector is floats[n].
export const rows: Row[] = Array.from({ length: 12 }, (_, n) => ({
	n,
	id: `deck${Math.floor(n / 2)}-0${(n % 2) + 1}`,
	deck_id: `deck${Math.floor(n / 2)}`,
	archetype: ARCHETYPES[n % 3],
	industry: INDUSTRIES[Math.floor(n / 2) % 2],
	data_type: n % 4 === 0 ? "kpi-numbers" : "time-series",
	purpose: `Show the ${TOPICS[n % 6]}`,
	why_it_works: `One highlighted element carries the ${TOPICS[(n + 1) % 6]} story`,
	description: `${ARCHETYPES[n % 3]} slide about ${TOPICS[n % 6]}`,
}));
export const floats: number[][] = rows.map((r) => {
	const next = rng(r.n + 1);
	return Array.from({ length: DIMS }, next);
});

export const manifest: Manifest = {
	library_version: "bge-m3/desc-v1/fixture",
	model: "@cf/baai/bge-m3",
	pooling: "cls",
	dims: DIMS,
	count: rows.length,
	ids: rows.map((r) => r.id),
};

export function buffers() {
	const vecs = new Int8Array(rows.length * DIMS);
	const norms = new Float32Array(rows.length);
	floats.forEach((f, n) => {
		const q = quantise(f);
		vecs.set(q, n * DIMS);
		norms[n] = Math.hypot(...q);
	});
	return { vecs: vecs.buffer, norms: norms.buffer };
}

export function library(m: Manifest = manifest) {
	const { vecs, norms } = buffers();
	return loadLibrary(dot, vecs, norms, m);
}

export async function seed(db: D1Database, version = manifest.library_version) {
	await db.batch([
		...SCHEMA.map((s) => db.prepare(s)),
		...rows.flatMap((r) => [
			db.prepare("INSERT INTO slides VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)").bind(r.n, r.id, r.deck_id, r.archetype, r.industry, r.data_type, r.purpose, r.why_it_works, r.description, JSON.stringify(r)),
			db.prepare("INSERT INTO slides_fts (rowid, purpose, why_it_works, description) VALUES (?, ?, ?, ?)").bind(r.n, r.purpose, r.why_it_works, r.description),
		]),
		db.prepare("INSERT INTO meta VALUES ('library_version', ?)").bind(version),
		db.prepare("DELETE FROM search_cache"),
	]);
}

// Workers AI stand-in: bge-m3 returns `embed(text)`, the reranker returns `rerank(query, texts)`. Calls are recorded.
export function fakeAI(embed: (text: string) => number[], rerank: (query: string, texts: string[]) => number[] = (_, t) => t.map(() => 0.5), pooling = "cls") {
	const calls: { model: string; input: any }[] = [];
	const ai = {
		calls,
		async run(model: string, input: any) {
			calls.push({ model, input });
			if (model === "@cf/baai/bge-m3") {
				const data = input.text.map(embed);
				return { shape: [data.length, DIMS], data, pooling };
			}
			if (model === "@cf/baai/bge-reranker-base") {
				const scores = rerank(input.query, input.contexts.map((c: { text: string }) => c.text));
				return { response: scores.map((score, id) => ({ id, score })).sort((a, b) => b.score - a.score) };
			}
			throw new Error(`unexpected model ${model}`);
		},
	};
	return ai;
}

// Nudge a row's vector so the query lands nearest to it.
export const near = (n: number, jitter = 0.05) => {
	const next = rng(1000 + n);
	return floats[n].map((x) => x + jitter * next());
};
