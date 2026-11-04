// Worker entry. The library build is bundled at deploy time (library/ stays gitignored)
// and checked at startup, so a mismatched build fails the deploy.
import dot from "./dot.wasm";
import vecs from "../../library/vecs.bin";
import norms from "../../library/norms.bin";
import manifest from "../../library/manifest.json";
import { app } from "./app";
import { loadLibrary } from "./search";

export { Limiter } from "./app";
export default app(loadLibrary(dot, vecs, norms, manifest));
