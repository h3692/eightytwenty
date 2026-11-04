// Worker entry. The library build is bundled at deploy time (library/ stays gitignored) and checked at startup, so a
// mismatched build fails the deploy. The MCP tools that call search(env, library, ...) arrive in S7.
import dot from "./dot.wasm";
import vecs from "../../library/vecs.bin";
import norms from "../../library/norms.bin";
import manifest from "../../library/manifest.json";
import { loadLibrary } from "./search";

const library = loadLibrary(dot, vecs, norms, manifest);

export default {
	async fetch() {
		return new Response(`Not found (library ${library.manifest.library_version})`, { status: 404 });
	},
} satisfies ExportedHandler<Env>;
