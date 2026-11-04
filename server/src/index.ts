// Worker entry. The library build is bundled at deploy time (library/ stays gitignored)
// and checked at startup, so a mismatched build fails the deploy.
import dot from "./dot.wasm";
import vecs from "../../library/vecs.bin";
import norms from "../../library/norms.bin";
import manifest from "../../library/manifest.json";
import { app, searcher } from "./app";
import { loadLibrary } from "./search";

const lib = loadLibrary(dot, vecs, norms, manifest);
export { Limiter } from "./app";
export const Searcher = searcher(lib);
export default app(lib);
