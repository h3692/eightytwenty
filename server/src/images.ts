// Image search for decks: public-domain logo SVGs (Wikimedia Commons, Simple Icons through Iconify), permissive icon
// SVGs (Iconify) and CC0 / public-domain / CC BY photos (Openverse). Only these fixed hosts are called and the query is
// only ever a URL-encoded search term; a failing source is named in `unavailable` while the others still answer.
export type Kind = "logo" | "icon" | "photo";
export type ImageResult = { title: string; licence: string; svg?: string; png_url?: string; note?: string; creator?: string; download_url?: string; landing_url?: string; credit?: string; thumbnail?: number };
type Thumbnail = { data: string; mimeType: string };
export type Images = { results: ImageResult[]; thumbnails: Thumbnail[]; unavailable: string[] };
// `token` is the caller's per-isolate cache of the Openverse app token, refreshed in place.
export type ImageDeps = { fetch: typeof fetch; openverse?: { clientId: string; clientSecret: string }; token?: { value?: string; expires?: number } };

const UA = "eightytwenty/1.0 (+https://eightytwenty.socratic.workers.dev/docs)";
const TIMEOUT = 8000, MAX_SVG = 12 * 1024, MAX_THUMB = 60 * 1024, MAX_TEXT = 40 * 1024, THUMBS = 3;
const MAX_THUMBS = 90_000; // base64 characters of all thumbnails: a response stays well under claude.ai's ~150k-character tool result
const DEFAULT_K: Record<Kind, number> = { logo: 3, icon: 4, photo: 3 };
const OPENVERSE = "https://api.openverse.org/";
const ICON_LICENCES = new Map([["tabler", "MIT"], ["lucide", "ISC"], ["ph", "MIT"], ["mdi", "Apache-2.0"], ["heroicons", "MIT"], ["material-symbols", "Apache-2.0"], ["carbon", "Apache-2.0"], ["simple-icons", "CC0"]]);
const COMMONS_LICENCES = new Map([["pd", "Public domain"], ["cc0", "CC0"]]);
const PHOTO_LICENCES = new Map([["cc0", "CC0"], ["pdm", "Public Domain Mark"], ["by", "CC BY"]]); // never BY-SA, NC or ND

// Rasterisers fetch external references, so anything that could reach outside the file rejects the whole SVG.
const UNSAFE = [/\\/, /<script/i, /foreignObject/i, /\son[a-z]+\s*=/i, /<!DOCTYPE/i, /<!ENTITY/i, /@import/i, /url\(\s*(?!['"]?#)/i,
	/href\s*=\s*(?!["']\s*(#|data:image\/(png|jpe?g|gif|webp)[;,]))/i, /attributeName\s*=\s*["']?[\w:]*href/i];
// Character references are decoded first (the XML parser does so before CSS sees them); any backslash rejects, since CSS
// escapes such as \75rl( spell url(.
// A reference past U+10FFFF is not well-formed XML: it decodes to a backslash, which rejects.
const decoded = (svg: string) => svg.replace(/&#(x?)([0-9a-f]+);?/gi, (_, x, n) => {
	const c = parseInt(n, x ? 16 : 10) || 0;
	return c > 0x10ffff ? "\\" : String.fromCodePoint(c);
});
export const safeSvg = (svg: string) => /<svg[\s>/]/i.test(svg) && !UNSAFE.some((re) => re.test(decoded(svg)));

async function get(deps: ImageDeps, url: string, init: RequestInit = {}) {
	const res = await deps.fetch(url, { ...init, headers: { "user-agent": UA, ...(init.headers as Record<string, string>) }, signal: AbortSignal.timeout(TIMEOUT) });
	if (!res.ok) throw Object.assign(new Error(`${new URL(url).host} answered ${res.status}`), { status: res.status });
	return res;
}

// The SVG text, or null when it is over 12 KB or unsafe (that one result is dropped). A failed download also drops it,
// but calls `missed`, so the answer is reported incomplete and not cached.
const fetchSvg = (deps: ImageDeps, url: string, missed: () => void) =>
	get(deps, url).then((r) => r.text()).then((s) => (s.length <= MAX_SVG && safeSvg(s) ? s : null), (e) => (e.status !== 404 && missed(), null)); // a 404 is a file that does not exist, not a failure

type Page = { title: string; index: number; imageinfo?: { size: number; url: string; thumburl?: string; mime: string; extmetadata?: Record<string, { value: string } | undefined> }[] };

async function commons(deps: ImageDeps, query: string, k: number, missed: () => void): Promise<ImageResult[]> {
	const d = await (await get(deps, `https://commons.wikimedia.org/w/api.php?action=query&format=json&generator=search&gsrnamespace=6&gsrlimit=10&gsrsearch=${encodeURIComponent(`${query} logo filemime:image/svg+xml`)}&prop=imageinfo&iiprop=url|size|mime|extmetadata&iiurlwidth=500`))
		.json<{ error?: { info: string }; query?: { pages: Record<string, Page> } }>();
	if (d.error) throw new Error(d.error.info);
	// pages come keyed by page id; `index` is the search rank. Over-size files are skipped before any download.
	const files = Object.values(d.query?.pages ?? {}).sort((a, b) => a.index - b.index).flatMap((p) => {
		const i = p.imageinfo?.[0], m = i?.extmetadata ?? {};
		const licence = COMMONS_LICENCES.get(m.License?.value.toLowerCase() ?? "");
		// Commons marks CC0 files Copyrighted (the author holds it and waives it); public-domain ones must be False
		return i && licence && (licence === "CC0" || m.Copyrighted?.value === "False") && i.mime === "image/svg+xml" && i.size <= MAX_SVG && new URL(i.url).host === "upload.wikimedia.org" ? [{ p, i, m, licence }] : [];
	}).slice(0, k);
	const svgs = await Promise.all(files.map(({ i }) => fetchSvg(deps, i.url, missed)));
	return files.flatMap(({ p, i, m, licence }, n) => (svgs[n] ? [{ title: p.title.replace(/^File:/, ""), licence, svg: svgs[n], png_url: i.thumburl, ...(m.Restrictions?.value && { note: m.Restrictions.value }) }] : []));
}

// Iconify search (its minimum is 32 results) sliced to k; only the permissive sets, by a strict id, are fetched.
// `exact` ids go first and may not exist (a 404 just drops them), so one extra is fetched for each.
async function iconify(deps: ImageDeps, query: string, k: number, prefixes: string, missed: () => void, exact: string[] = []): Promise<ImageResult[]> {
	const { icons } = await (await get(deps, `https://api.iconify.design/search?query=${encodeURIComponent(query)}&limit=32&prefixes=${prefixes}`)).json<{ icons: string[] }>();
	const ids = [...new Set([...exact, ...icons])].filter((id) => /^[a-z0-9-]+:[a-z0-9-]+$/.test(id) && ICON_LICENCES.has(id.split(":")[0])).slice(0, k + exact.length);
	const svgs = await Promise.all(ids.map((id) => fetchSvg(deps, `https://api.iconify.design/${id.replace(":", "/")}.svg`, missed)));
	return ids.flatMap((id, n) => (svgs[n] ? [{ title: id, licence: ICON_LICENCES.get(id.split(":")[0])!, svg: svgs[n] }] : [])).slice(0, k);
}

// With app credentials, the OAuth2 client-credentials token, minted again within 60 s of expiry; else, or when minting
// fails, anonymous (the shared anonymous quota may still answer).
async function bearer(deps: ImageDeps): Promise<Record<string, string>> {
	if (!deps.openverse) return {};
	const token = deps.token ?? {};
	if (!token.value || Date.now() > (token.expires ?? 0) - 60_000) {
		const body = new URLSearchParams({ grant_type: "client_credentials", client_id: deps.openverse.clientId, client_secret: deps.openverse.clientSecret });
		try {
			const { access_token, expires_in } = await (await get(deps, `${OPENVERSE}v1/auth_tokens/token/`, { method: "POST", body })).json<{ access_token?: string; expires_in: number }>();
			if (typeof access_token !== "string") throw new Error("Openverse sent no access token");
			Object.assign(token, { value: access_token, expires: Date.now() + expires_in * 1000 });
		} catch {
			return {};
		}
	}
	return { authorization: `Bearer ${token.value}` };
}

async function thumbnail(deps: ImageDeps, url: string | null, headers: Record<string, string>, missed: () => void): Promise<Thumbnail | null> {
	if (!url?.startsWith(OPENVERSE)) return null;
	try {
		const res = await get(deps, `${url}?compressed=true`, { headers }); // compressed is Openverse's default today; asked for explicitly
		const bytes = new Uint8Array(await res.arrayBuffer()), mimeType = res.headers.get("content-type") ?? "";
		return bytes.length <= MAX_THUMB && mimeType.startsWith("image/") ? { data: btoa(String.fromCharCode(...bytes)), mimeType } : null;
	} catch {
		missed();
		return null;
	}
}

type Photo = { title: string; creator: string | null; license: string; license_version: string | null; url: string; foreign_landing_url: string; thumbnail: string | null; attribution: string };

async function photos(deps: ImageDeps, query: string, k: number, missed: () => void): Promise<Omit<Images, "unavailable">> {
	const headers = await bearer(deps);
	const { results } = await (await get(deps, `${OPENVERSE}v1/images/?q=${encodeURIComponent(query)}&license=cc0,pdm,by&page_size=${k}`, { headers })).json<{ results: Photo[] }>();
	const kept = results.filter((r) => PHOTO_LICENCES.has(r.license)).slice(0, k);
	const thumbs = await Promise.all(kept.slice(0, THUMBS).map((r) => thumbnail(deps, r.thumbnail, headers, missed)));
	const thumbnails: Thumbnail[] = [];
	let room = MAX_THUMBS;
	const fits = (t: Thumbnail | null | undefined) => !!t && t.data.length <= room && ((room -= t.data.length), true); // one too big is skipped, later ones may fit
	return {
		results: kept.map((r, n) => ({
			title: r.title, creator: r.creator ?? undefined,
			licence: `${PHOTO_LICENCES.get(r.license)}${r.license_version ? ` ${r.license_version}` : ""}`,
			download_url: r.url, landing_url: r.foreign_landing_url,
			...(r.license === "by" && { credit: r.attribution }), // only CC BY requires credit
			...(fits(thumbs[n]) && { thumbnail: thumbnails.push(thumbs[n]!) - 1 }), // its position in `thumbnails`
		})),
		thumbnails,
	};
}

export async function findImages(kind: Kind, query: string, k = DEFAULT_K[kind], deps: ImageDeps): Promise<Images> {
	const unavailable: string[] = [];
	let incomplete = false;
	const missed = () => void (incomplete = true);
	const tried = <T>(name: string, p: Promise<T>, none: T) => p.catch(() => (unavailable.push(name), none));
	let found: Omit<Images, "unavailable">;
	if (kind === "photo") found = await tried("photos", photos(deps, query, k, missed), { results: [], thumbnails: [] });
	else if (kind === "icon") found = { results: await tried("icons", iconify(deps, query, k, [...ICON_LICENCES.keys()].join(","), missed), []), thumbnails: [] };
	else {
		const [c, s] = await Promise.all([tried("Wikimedia Commons", commons(deps, query, k, missed), []), tried("Simple Icons", iconify(deps, query, k, "simple-icons", missed, [`simple-icons:${query.toLowerCase().replace(/[^a-z0-9]/g, "")}`]), [])]);
		found = { results: [...c, ...s].slice(0, k), thumbnails: [] };
	}
	// at most 40 KB of SVG text per response: results stay in order and the rest is dropped
	const results: ImageResult[] = [];
	let size = 0;
	for (const r of found.results) {
		if ((size += r.svg?.length ?? 0) > MAX_TEXT) break;
		results.push(r);
	}
	if (incomplete && !unavailable.length) unavailable.push("some downloads"); // a reported gap keeps the answer out of the cache
	return { results, thumbnails: found.thumbnails, unavailable };
}
