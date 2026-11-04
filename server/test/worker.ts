// Test entry (vitest main): src/index.ts with the synthetic fixture library in place of the gitignored library/ build.
import { searcher } from "../src/app";
import { library } from "./fixture";

export { Limiter } from "../src/app";
export const Searcher = searcher(library());
