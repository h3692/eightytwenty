import { afterEach, describe, expect, it, vi } from "vitest";
import { findImages, safeSvg } from "../src/images";
import cocaColaLogo from "./fixtures/images/coca-cola-logo.svg";
import thailand from "./fixtures/images/coca-cola-thailand.svg";
import commons from "./fixtures/images/commons-coca-cola.json";
import simpleCoke from "./fixtures/images/iconify-simple-icons-coca-cola.json";
import simpleGithub from "./fixtures/images/iconify-simple-icons-github.json";
import truck from "./fixtures/images/iconify-truck.json";
import mdiTruckOutline from "./fixtures/images/mdi_truck-outline.svg";
import mdiTruck from "./fixtures/images/mdi_truck.svg";
import openverse from "./fixtures/images/openverse-hospital.json";
import thumb from "./fixtures/images/openverse-thumb.json";
import cocacola from "./fixtures/images/simple-icons_cocacola.svg";
import github from "./fixtures/images/simple-icons_github.svg";
import tablerTruckFilled from "./fixtures/images/tabler_truck-filled.svg";
import tablerTruck from "./fixtures/images/tabler_truck.svg";
import company2020 from "./fixtures/images/the-coca-cola-company-2020.svg";

// Fixtures are real responses captured from the three APIs (trimmed); the Coca-Cola search mixes public-domain logos
// with CC BY 4.0 uploads and two files over 12 KB. openverse-thumb.json keeps only the status and headers of a real
// compressed thumbnail (the JPEG itself is left out).
const UA = "eightytwenty/1.0 (+https://eightytwenty.socratic.workers.dev/docs)";
const COMMONS = (q: string) => `https://commons.wikimedia.org/w/api.php?action=query&format=json&generator=search&gsrnamespace=6&gsrlimit=10&gsrsearch=${encodeURIComponent(`${q} logo filemime:image/svg+xml`)}&prop=imageinfo&iiprop=url|size|mime|extmetadata&iiurlwidth=500`;
const SIMPLE = (q: string) => `https://api.iconify.design/search?query=${encodeURIComponent(q)}&limit=32&prefixes=simple-icons`;
const ICONS = (q: string) => `https://api.iconify.design/search?query=${encodeURIComponent(q)}&limit=32&prefixes=tabler,lucide,ph,mdi,heroicons,material-symbols,carbon,simple-icons`;
const ICON = (id: string) => `https://api.iconify.design/${id.replace(":", "/")}.svg`;
const PHOTOS = (q: string, k: number) => `https://api.openverse.org/v1/images/?q=${encodeURIComponent(q)}&license=cc0,pdm,by&page_size=${k}`;
const MINT = "https://api.openverse.org/v1/auth_tokens/token/";
const THUMB = (url: string) => `${url}?compressed=true`;
const HOSTS = ["commons.wikimedia.org", "upload.wikimedia.org", "api.iconify.design", "api.openverse.org"];

type Routes = Record<string, (init: RequestInit) => Response | Promise<Response>>;
const json = (body: unknown) => () => Response.json(body);
const svg = (text: string) => () => new Response(text, { headers: { "content-type": "image/svg+xml" } });
const jpeg = (bytes: Uint8Array<ArrayBuffer>) => () => new Response(bytes, { headers: { "content-type": "image/jpeg" } });
const big = (bytes: number) => `<svg xmlns="http://www.w3.org/2000/svg"><path d="${"M0 0".repeat(bytes / 4)}"/></svg>`;
const page = (title: string, data = commons) => Object.values(data.query.pages).find((p) => p.title === `File:${title}`)!.imageinfo[0];

// A fetch serving exact URLs only (anything else is a 404), recording every call.
function fake(routes: Routes) {
	const calls: { url: string; init: RequestInit }[] = [];
	const fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
		const url = String(input);
		calls.push({ url, init });
		return routes[url]?.(init) ?? new Response("not found", { status: 404 });
	}) as typeof globalThis.fetch;
	return { fetch, calls };
}
const header = (init: RequestInit, name: string) => new Headers(init.headers).get(name);

const cokeRoutes = (data = commons): Routes => ({
	[COMMONS("Coca-Cola")]: json(data),
	[page("The Coca-Cola Company (2020).svg").url]: svg(company2020),
	[page("Coca-Cola logo.svg").url]: svg(cocaColaLogo),
	[page("Coca-Cola Thailand.svg").url]: svg(thailand),
	[SIMPLE("Coca-Cola")]: json(simpleCoke),
});
const githubRoutes: Routes = Object.fromEntries([[SIMPLE("GitHub"), json(simpleGithub)], ...simpleGithub.icons.map((id) => [ICON(id), svg(id === "simple-icons:github" ? github : `<svg xmlns="http://www.w3.org/2000/svg" id="${id}"/>`)])]);
const truckRoutes: Routes = {
	[ICONS("truck")]: json(truck),
	[ICON("mdi:truck")]: svg(mdiTruck),
	[ICON("mdi:truck-outline")]: svg(mdiTruckOutline),
	[ICON("tabler:truck")]: svg(tablerTruck),
	[ICON("tabler:truck-filled")]: svg(tablerTruckFilled),
};
const thumbBytes = (n: number) => Uint8Array.from({ length: n }, (_, i) => i % 256);
const base64 = (bytes: Uint8Array) => btoa(String.fromCharCode(...bytes));
const photoRoutes = (data = openverse, k = 4): Routes => ({
	[PHOTOS("busy hospital waiting room", k)]: json(data),
	...Object.fromEntries(data.results.map((r, i) => [THUMB(r.thumbnail), jpeg(thumbBytes(100 + i))])),
});

afterEach(() => vi.restoreAllMocks());

describe("logos", () => {
	it("keeps public-domain Commons SVGs, drops the CC BY ones and never fetches files over 12 KB", async () => {
		const { fetch, calls } = fake(cokeRoutes());
		const r = await findImages("logo", "Coca-Cola", 3, { fetch });
		expect(r).toEqual({
			results: [
				{ title: "The Coca-Cola Company (2020).svg", licence: "Public domain", svg: company2020, png_url: page("The Coca-Cola Company (2020).svg").thumburl, note: "trademarked" },
				{ title: "Coca-Cola logo.svg", licence: "Public domain", svg: cocaColaLogo, png_url: page("Coca-Cola logo.svg").thumburl, note: "trademarked" },
			],
			thumbnails: [],
			unavailable: [],
		});
		const fetched = calls.map((c) => c.url);
		for (const title of ["Coca-Cola Thailand.svg", "Coca-Cola China.svg", "The Coca-Cola Company logo.svg", "Coca-Cola logo araby.svg"])
			expect(fetched).not.toContain(page(title).url);
	});

	it("keeps CC0 whatever its case even though Commons marks CC0 files Copyrighted, and other files only when not copyrighted", async () => {
		const data = structuredClone(commons);
		// a real CC0 file (File:Hungertent Logo 2021.svg) carries License cc0 with Copyrighted True
		Object.assign(page("Coca-Cola Thailand.svg", data).extmetadata, { License: { value: "CC0" }, Copyrighted: { value: "True" } });
		Object.assign(page("The Coca-Cola Company (2020).svg", data).extmetadata, { Copyrighted: { value: "True" } });
		const { fetch } = fake(cokeRoutes(data));
		const r = await findImages("logo", "Coca-Cola", 3, { fetch });
		expect(r.results.map((x) => [x.title, x.licence])).toEqual([["Coca-Cola Thailand.svg", "CC0"], ["Coca-Cola logo.svg", "Public domain"]]);
	});

	it("drops a Commons SVG that turns out larger than 12 KB or unsafe", async () => {
		const { fetch } = fake({ ...cokeRoutes(), [page("The Coca-Cola Company (2020).svg").url]: svg(big(13 * 1024)), [page("Coca-Cola logo.svg").url]: svg('<svg><script>alert(1)</script></svg>') });
		expect((await findImages("logo", "Coca-Cola", 3, { fetch })).results).toEqual([]);
	});

	it("combines Commons and Simple Icons up to k, with no credit", async () => {
		// the Coca-Cola Commons answer stands in for a GitHub one
		const { fetch } = fake({ ...githubRoutes, [COMMONS("GitHub")]: json(commons), [page("The Coca-Cola Company (2020).svg").url]: svg(company2020), [page("Coca-Cola logo.svg").url]: svg(cocaColaLogo) });
		const r = await findImages("logo", "GitHub", 3, { fetch });
		expect(r.results.map((x) => x.title)).toEqual(["The Coca-Cola Company (2020).svg", "Coca-Cola logo.svg", "simple-icons:github"]);
		expect(r.results[2]).toEqual({ title: "simple-icons:github", licence: "CC0", svg: github });
		expect(r.results.some((x) => "credit" in x)).toBe(false);
		expect((await findImages("logo", "GitHub", 1, { fetch })).results.map((x) => x.title)).toEqual(["The Coca-Cola Company (2020).svg"]);
	});

	it("also looks up the Simple Icons id made of the query's letters and digits, fetching each icon once", async () => {
		const { fetch, calls } = fake({ ...cokeRoutes(), [ICON("simple-icons:cocacola")]: svg(cocacola) });
		const r = await findImages("logo", "Coca-Cola", 3, { fetch });
		expect(r.results.map((x) => x.title)).toEqual(["The Coca-Cola Company (2020).svg", "Coca-Cola logo.svg", "simple-icons:cocacola"]);
		expect(r.results[2]).toEqual({ title: "simple-icons:cocacola", licence: "CC0", svg: cocacola });
		const gh = fake({ ...githubRoutes, [COMMONS("GitHub")]: json({ batchcomplete: "" }) });
		expect((await findImages("logo", "GitHub", 3, gh)).results.map((x) => x.title)).toEqual(["simple-icons:github", "simple-icons:githubpages", "simple-icons:githubactions"]);
		expect(gh.calls.filter((c) => c.url === ICON("simple-icons:github"))).toHaveLength(1);
		const missing = fake(cokeRoutes()); // no such icon: a 404, and the result is simply absent
		expect((await findImages("logo", "Coca-Cola", 3, missing)).results).toHaveLength(2);
		expect(missing.calls.map((c) => c.url)).toContain(ICON("simple-icons:cocacola"));
	});

	it("defaults to 3 logos", async () => {
		const { fetch } = fake({ ...githubRoutes, [COMMONS("GitHub")]: json({ batchcomplete: "" }) });
		expect((await findImages("logo", "GitHub", undefined, { fetch })).results).toHaveLength(3);
	});

	it("one logo source failing leaves the other answering", async () => {
		const commonsDown = fake({ ...githubRoutes, [COMMONS("GitHub")]: json({ error: { code: "internal_api_error_DBQueryError", info: "Database query error." } }) });
		const r = await findImages("logo", "GitHub", 3, commonsDown);
		expect(r.unavailable).toEqual(["Wikimedia Commons"]);
		expect(r.results.map((x) => x.title)).toEqual(["simple-icons:github", "simple-icons:githubpages", "simple-icons:githubactions"]);

		const iconifyDown = fake({ ...cokeRoutes(), [SIMPLE("Coca-Cola")]: () => new Response("upstream request timeout", { status: 504 }) });
		const s = await findImages("logo", "Coca-Cola", 3, iconifyDown);
		expect(s.unavailable).toEqual(["Simple Icons"]);
		expect(s.results).toHaveLength(2);
	});
});

describe("icons", () => {
	it("returns the first k icons as SVG text with their set's licence, never a credit", async () => {
		const { fetch, calls } = fake(truckRoutes);
		const r = await findImages("icon", "truck", undefined, { fetch });
		expect(r).toEqual({
			results: [
				{ title: "mdi:truck", licence: "Apache-2.0", svg: mdiTruck },
				{ title: "mdi:truck-outline", licence: "Apache-2.0", svg: mdiTruckOutline },
				{ title: "tabler:truck", licence: "MIT", svg: tablerTruck },
				{ title: "tabler:truck-filled", licence: "MIT", svg: tablerTruckFilled },
			],
			thumbnails: [],
			unavailable: [],
		});
		expect(calls).toHaveLength(5);
	});

	it("slices the 32 search results down to k", async () => {
		const { fetch, calls } = fake(truckRoutes);
		expect((await findImages("icon", "truck", 2, { fetch })).results.map((x) => x.title)).toEqual(["mdi:truck", "mdi:truck-outline"]);
		expect(calls).toHaveLength(3);
	});

	it("never fetches icons outside the permissive sets or with odd names", async () => {
		const { fetch, calls } = fake({ [ICONS("truck")]: json({ icons: ["fa6-brands:github", "mdi:../../x", "lucide:truck"] }), [ICON("lucide:truck")]: svg(mdiTruck) });
		const r = await findImages("icon", "truck", 4, { fetch });
		expect(r.results).toEqual([{ title: "lucide:truck", licence: "ISC", svg: mdiTruck }]);
		expect(calls.map((c) => c.url)).toEqual([ICONS("truck"), ICON("lucide:truck")]);
	});

	it("drops unsafe and oversized SVGs", async () => {
		const { fetch } = fake({ ...truckRoutes, [ICON("mdi:truck")]: svg('<svg><image href="http://evil.example/x.png"/></svg>'), [ICON("tabler:truck")]: svg(big(13 * 1024)) });
		expect((await findImages("icon", "truck", 4, { fetch })).results.map((x) => x.title)).toEqual(["mdi:truck-outline", "tabler:truck-filled"]);
	});

	it("keeps results in order until their SVG text would pass 40 KB", async () => {
		const { fetch } = fake(Object.fromEntries(Object.entries(truckRoutes).map(([url, route]) => [url, url === ICONS("truck") ? route : svg(big(11 * 1024))])));
		expect((await findImages("icon", "truck", 4, { fetch })).results.map((x) => x.title)).toEqual(["mdi:truck", "mdi:truck-outline", "tabler:truck"]);
	});

	it("an Iconify failure makes icons unavailable", async () => {
		const { fetch } = fake({ [ICONS("truck")]: () => new Response("<html>Bad gateway</html>", { status: 502 }) });
		expect(await findImages("icon", "truck", 4, { fetch })).toEqual({ results: [], thumbnails: [], unavailable: ["icons"] });
	});
});

describe("photos", () => {
	it("returns links, credit only for CC BY, and up to 3 thumbnails, anonymously without app credentials", async () => {
		const { fetch, calls } = fake(photoRoutes());
		const r = await findImages("photo", "busy hospital waiting room", 4, { fetch });
		const [by, , pdm] = openverse.results;
		expect(r.results).toHaveLength(4);
		expect(r.results[0]).toEqual({ title: by.title, creator: by.creator, licence: "CC BY 2.0", download_url: by.url, landing_url: by.foreign_landing_url, credit: by.attribution, thumbnail: 0 });
		expect(r.results[2]).toEqual({ title: pdm.title, creator: pdm.creator, licence: "Public Domain Mark 1.0", download_url: pdm.url, landing_url: pdm.foreign_landing_url, thumbnail: 2 });
		expect(r.results.map((x) => !!x.credit)).toEqual([true, true, false, false]);
		expect(r.thumbnails).toEqual([0, 1, 2].map((i) => ({ data: base64(thumbBytes(100 + i)), mimeType: "image/jpeg" })));
		expect(r.unavailable).toEqual([]);
		expect(calls.map((c) => c.url)).not.toContain(THUMB(openverse.results[3].thumbnail));
		expect(calls.every((c) => header(c.init, "authorization") === null)).toBe(true);
	});

	it("asks only for CC0, public domain and CC BY, and drops BY-SA, NC and ND if they come back anyway", async () => {
		const data = structuredClone(openverse);
		data.results[0].license = "by-sa";
		data.results[1].license = "by-nc";
		data.results[2].license = "by-nd";
		const { fetch, calls } = fake(photoRoutes(data));
		const r = await findImages("photo", "busy hospital waiting room", 4, { fetch });
		expect(new URL(calls[0].url).searchParams.get("license")).toBe("cc0,pdm,by");
		expect(r.results.map((x) => x.title)).toEqual([openverse.results[3].title]);
		expect(r.results[0].licence).toBe("Public Domain Mark 1.0");
	});

	it("labels CC0 and defaults to 3 photos", async () => {
		const data = structuredClone(openverse);
		data.results = data.results.slice(0, 3);
		data.results[2].license = "cc0";
		const { fetch } = fake(photoRoutes(data, 3));
		const r = await findImages("photo", "busy hospital waiting room", undefined, { fetch });
		expect(r.results.map((x) => x.licence)).toEqual(["CC BY 2.0", "CC BY 2.0", "CC0 1.0"]);
		expect(r.results[2].credit).toBeUndefined();
	});

	it("skips thumbnails over 60 KB and any not on api.openverse.org", async () => {
		const data = structuredClone(openverse);
		data.results[1].thumbnail = "https://evil.example/thumb.jpg";
		const { fetch, calls } = fake({ ...photoRoutes(data), [THUMB(data.results[0].thumbnail)]: jpeg(thumbBytes(60 * 1024 + 1)), [THUMB(data.results[2].thumbnail)]: jpeg(thumbBytes(60 * 1024)) });
		const r = await findImages("photo", "busy hospital waiting room", 4, { fetch });
		expect(r.thumbnails).toEqual([{ data: base64(thumbBytes(60 * 1024)), mimeType: "image/jpeg" }]);
		expect(r.results.map((x) => x.thumbnail)).toEqual([undefined, undefined, 0, undefined]);
		expect(calls.map((c) => c.url)).not.toContain("https://evil.example/thumb.jpg");
	});

	it("asks for the compressed thumbnail and fits as many as its base64 allows in 90,000 characters, skipping one too big for the rest", async () => {
		const real = Number(thumb.headers["content-length"]); // 51,312 base64 characters: a second one that size would pass 90,000
		expect(thumb.url).toBe(THUMB(openverse.results[0].thumbnail));
		const sized = (...sizes: number[]) => fake({ ...photoRoutes(), ...Object.fromEntries(sizes.map((n, i) => [THUMB(openverse.results[i].thumbnail), jpeg(thumbBytes(n))])) });
		const two = await findImages("photo", "busy hospital waiting room", 4, sized(real, real, 1000));
		expect(two.thumbnails.map((t) => t.data)).toEqual([base64(thumbBytes(real)), base64(thumbBytes(1000))]);
		expect(two.results.map((x) => x.thumbnail)).toEqual([0, undefined, 1, undefined]); // the second does not fit, the small third does
		const live = await findImages("photo", "busy hospital waiting room", 4, sized(38_482, 33_874, 25_304)); // the live sizes for this query
		expect(live.results.map((x) => x.thumbnail)).toEqual([0, undefined, 1, undefined]);
		const three = await findImages("photo", "busy hospital waiting room", 4, sized(30_000, 30_000, 30_000));
		expect(three.thumbnails.map((t) => t.data.length)).toEqual([40_000, 40_000]);
		expect(three.results.map((x) => x.thumbnail)).toEqual([0, 1, undefined, undefined]);
	});

	it("an Openverse 504 with a plain-text body makes photos unavailable while logos still answer", async () => {
		const { fetch } = fake({ ...cokeRoutes(), [PHOTOS("busy hospital waiting room", 3)]: () => new Response("upstream request timeout", { status: 504, headers: { "content-type": "text/plain" } }) });
		expect(await findImages("photo", "busy hospital waiting room", 3, { fetch })).toEqual({ results: [], thumbnails: [], unavailable: ["photos"] });
		const logos = await findImages("logo", "Coca-Cola", 3, { fetch });
		expect(logos.unavailable).toEqual([]);
		expect(logos.results).toHaveLength(2);
	});

	it("a non-JSON 200 or a timeout makes photos unavailable", async () => {
		const notJson = fake({ [PHOTOS("x", 3)]: () => new Response("upstream request timeout") });
		expect((await findImages("photo", "x", 3, notJson)).unavailable).toEqual(["photos"]);
		const timeout = { fetch: (async () => { throw new DOMException("The operation was aborted due to timeout", "TimeoutError"); }) as typeof fetch };
		expect(await findImages("photo", "x", 3, timeout)).toEqual({ results: [], thumbnails: [], unavailable: ["photos"] });
	});
});

describe("Openverse app token", () => {
	const app = { clientId: "app-id", clientSecret: "app-key" };
	const minted = (value: string) => () => Response.json({ access_token: value, scope: "read write", expires_in: 36000, token_type: "Bearer" });

	it("mints a token with the app credentials, sends it as Bearer and reuses it", async () => {
		const { fetch, calls } = fake({ ...photoRoutes(), [MINT]: minted("tok-1") });
		const token = {};
		await findImages("photo", "busy hospital waiting room", 4, { fetch, openverse: app, token });
		await findImages("photo", "busy hospital waiting room", 4, { fetch, openverse: app, token });
		const posts = calls.filter((c) => c.url === MINT);
		expect(posts).toHaveLength(1);
		expect(posts[0].init.method).toBe("POST");
		expect(String(posts[0].init.body)).toBe("grant_type=client_credentials&client_id=app-id&client_secret=app-key");
		expect(calls.filter((c) => c.url !== MINT).every((c) => header(c.init, "authorization") === "Bearer tok-1")).toBe(true);
		expect(token).toEqual({ value: "tok-1", expires: expect.any(Number) });
	});

	it("refreshes the token after expiry or within 60 s of it, not before", async () => {
		for (const [left, refreshed] of [[-1000, true], [30_000, true], [120_000, false]] as const) {
			const { fetch, calls } = fake({ ...photoRoutes(), [MINT]: minted("tok-2") });
			const token = { value: "tok-1", expires: Date.now() + left };
			await findImages("photo", "busy hospital waiting room", 4, { fetch, openverse: app, token });
			expect(calls.some((c) => c.url === MINT)).toBe(refreshed);
			expect(header(calls.at(-1)!.init, "authorization")).toBe(refreshed ? "Bearer tok-2" : "Bearer tok-1");
			if (refreshed) expect(token.expires).toBeGreaterThan(Date.now() + 35_000_000);
		}
	});

	it("a failed token request falls back to an anonymous search", async () => {
		const { fetch, calls } = fake({ ...photoRoutes(), [MINT]: () => Response.json({ error: "invalid_client" }, { status: 401 }) });
		const r = await findImages("photo", "busy hospital waiting room", 4, { fetch, openverse: app, token: {} });
		expect(r.unavailable).toEqual([]);
		expect(r.results).toHaveLength(4);
		expect(calls.filter((c) => c.url !== MINT).every((c) => header(c.init, "authorization") === null)).toBe(true);
	});
});

describe("every request", () => {
	it("has an 8 s timeout, the descriptive user agent, and goes only to the fixed hosts", async () => {
		const timeout = vi.spyOn(AbortSignal, "timeout");
		const { fetch, calls } = fake({ ...cokeRoutes(), ...truckRoutes, ...photoRoutes(), [MINT]: () => Response.json({ access_token: "t", expires_in: 3600 }) });
		await findImages("logo", "Coca-Cola", 3, { fetch });
		await findImages("icon", "truck", 4, { fetch });
		await findImages("photo", "busy hospital waiting room", 4, { fetch, openverse: { clientId: "a", clientSecret: "b" }, token: {} });
		expect(calls.length).toBeGreaterThan(10);
		expect(timeout.mock.calls).toEqual(calls.map(() => [8000]));
		for (const { url, init } of calls) {
			expect(HOSTS).toContain(new URL(url).host);
			expect(header(init, "user-agent")).toBe(UA);
			expect(init.signal).toBeInstanceOf(AbortSignal);
		}
	});

	it("puts the query only in a URL-encoded search parameter", async () => {
		const { fetch, calls } = fake({});
		const q = "a&b=c/../#x?y";
		await findImages("logo", q, 3, { fetch });
		await findImages("icon", q, 3, { fetch });
		await findImages("photo", q, 3, { fetch });
		expect(calls.map((c) => c.url)).toEqual([COMMONS(q), SIMPLE(q), ICONS(q), PHOTOS(q, 3)]);
	});
});

describe("safeSvg", () => {
	it("accepts the real fixtures, including local url(#…) and xlink:href=\"#…\" references", () => {
		for (const s of [cocaColaLogo, company2020, thailand, mdiTruck, mdiTruckOutline, tablerTruck, tablerTruckFilled, github]) expect(safeSvg(s)).toBe(true);
		expect(safeSvg('<svg><image href="data:image/png;base64,iVBORw0KGgo="/></svg>')).toBe(true);
	});

	it("a thumbnail or SVG that fails to download marks the answer incomplete, so it is not cached; a rule-dropped one does not", async () => {
		const failing = fake({ ...photoRoutes(), [THUMB(openverse.results[0].thumbnail)]: () => new Response("", { status: 429 }) });
		const photo = await findImages("photo", "busy hospital waiting room", 4, failing);
		expect(photo.unavailable).toEqual(["some downloads"]);
		expect(photo.results).toHaveLength(4);
		const icon = await findImages("icon", "truck", 4, fake({ ...truckRoutes, [ICON("mdi:truck")]: () => new Response("", { status: 503 }) }));
		expect(icon.unavailable).toEqual(["some downloads"]);
		expect(icon.results.map((r) => r.title)).not.toContain("mdi:truck");
		const unsafe = await findImages("icon", "truck", 4, fake({ ...truckRoutes, [ICON("mdi:truck")]: svg("<svg><script>x</script></svg>") }));
		expect(unsafe.unavailable).toEqual([]);
	});

	it.each([
		["script", "<svg><script>alert(1)</script></svg>"],
		["foreignObject", "<svg><foreignObject><div/></foreignObject></svg>"],
		["an event handler", '<svg onload="alert(1)"/>'],
		["an event handler on a child", "<svg><rect onclick = 'x()'/></svg>"],
		["a DOCTYPE", '<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd"><svg/>'],
		["an entity", '<!ENTITY x SYSTEM "file:///etc/passwd"><svg>&x;</svg>'],
		["@import", "<svg><style>@import 'https://evil.example/a.css';</style></svg>"],
		["url( to http", '<svg><rect fill="url(http://evil.example/p.svg#g)"/></svg>'],
		["url( to file:", "<svg><style>rect { fill: url('file:///etc/passwd') }</style></svg>"],
		["an http href", '<svg><image href="http://evil.example/x.png"/></svg>'],
		["a file: xlink:href", '<svg><use xlink:href="file:///etc/passwd#x"/></svg>'],
		["an unquoted href", "<svg><a href=https://evil.example>x</a></svg>"],
		["a data:image/svg+xml href (nested SVG)", '<svg><image href="data:image/svg+xml;base64,PHN2Zy8+"/></svg>'],
		["a data:text/html href", '<svg><a href="data:text/html,<b>x</b>">x</a></svg>'],
		["an animation retargeting href", '<svg><a href="#a"><set attributeName="href" to="https://evil.example"/></a></svg>'],
		["text that is not an SVG", "<html><body>Bad gateway</body></html>"],
		["a CSS-escaped url(", "<svg><style>rect{fill:\\75rl(http://127.0.0.1:9/x.svg#p)}</style></svg>"],
		["a CSS-escaped @import", '<svg><style>@\\69mport "http://evil.example/a.css";</style></svg>'],
		["a decimal character reference for (", '<svg><rect style="fill:url&#40;http://evil.example/p)"/></svg>'],
		["a hex character reference for (", "<svg><style>rect{fill:url&#x28;http://evil.example/p)}</style></svg>"],
		["a character reference for @", '<svg><style>&#64;import "http://evil.example/a.css";</style></svg>'],
	])("rejects %s", (_, s) => expect(safeSvg(s)).toBe(false));
});
