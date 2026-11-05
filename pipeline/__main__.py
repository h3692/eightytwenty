"""python -m pipeline <stage> ...  (run from the repo root; outputs go to ./library/, which is gitignored)."""
import argparse
import sys

from pipeline import build, dedupe, embed, extract, flow, label_prep, leak_check, mockup, package


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m pipeline")
    sub = ap.add_subparsers(dest="stage", required=True)
    p = sub.add_parser("extract", help="render + extract a .pptx; prints the new deck_id")
    p.add_argument("deck")
    p.add_argument("--skip-render", action="store_true", help="no slide PNGs (when LibreOffice is missing)")
    p = sub.add_parser("reextract", help="re-extract a deck into its existing deck_id, keeping labels and renders")
    p.add_argument("deck_id")
    p.add_argument("deck")
    for name, help_ in (("label-prep", "write labeling worksheets"), ("build", "labels + geometry -> DNA, wireframe"),
                        ("leak-check", "check, write judge worksheet, promote passing records"),
                        ("flow-prep", "write the deck-flow worksheet and contact sheet"),
                        ("flow-build", "flow.json + labels -> deck-flow record")):
        sub.add_parser(name, help=help_).add_argument("deck_id")
    sub.choices["flow-prep"].add_argument("--impact-only", action="store_true",
                                          help="worksheet to add impact marks to an existing flow.json, nothing else")
    p = sub.add_parser("embed", help="embed published descriptions via the local Worker")
    p.add_argument("--url", default=f"http://127.0.0.1:{embed.PORT}")
    sub.add_parser("package", help="write records.sql and copy wireframes for deploy")
    sub.add_parser("exclusions", help="write work/dedupe-report.txt and work/blank-report.txt (never published)")
    p = sub.add_parser("layout-prep", help="write component layout worksheets only, for slides labelled before")
    p.add_argument("deck_id")
    p.add_argument("--slides", help="comma-separated slide numbers, e.g. 05,08 (default: all)")
    p = sub.add_parser("mockup", help="build v3 component layouts into mockup .pptx templates and PNGs")
    p.add_argument("deck_id")
    p.add_argument("--slides", help="comma-separated slide numbers, e.g. 05,08 (default: all)")
    for p in sub.choices.values():
        p.add_argument("--library", default="library")
    a = ap.parse_args(argv)

    if a.stage == "extract":
        print(f"deck_id {extract.run(a.deck, a.library, render=not a.skip_render)}")
    elif a.stage == "reextract":
        print(f"deck_id {extract.run(a.deck, a.library, render=False, deck_id=a.deck_id)}")
        print("\n".join(label_prep.reconcile(a.deck_id, a.library)) or "labels: all regions still match")
    elif a.stage == "label-prep":
        work = label_prep.run(a.deck_id, a.library)
        print(f"Label and draw each slide: in Claude Code, ask it to follow every {work}/slide-NN.prompt.txt")
    elif a.stage == "build":
        print("\n".join(build.run(a.deck_id, a.library)))
    elif a.stage == "leak-check":
        report = leak_check.run(a.deck_id, a.library)
        for rid, r in report.items():
            print(rid, f"auto={r['auto']}", f"judge={r['judge']}", *r["problems"], sep="  ")
        if not all(r["published"] or r.get("excluded") for r in report.values()):
            print(f"Not published: fix labels and rebuild, or judge in a fresh session (library/judge/{a.deck_id}/JUDGE.txt).")
            sys.exit(1)
    elif a.stage in ("flow-prep", "flow-build"):
        out = flow.prep(a.deck_id, a.library, a.impact_only) if a.stage == "flow-prep" else \
            flow.build_flow(a.deck_id, a.library)
        if out is None:
            print(f"{a.deck_id}: fewer than {flow.MIN_SLIDES} visible slides, no deck flow (skipped)")
        elif a.stage == "flow-prep":
            print(f"Write the deck flow: in Claude Code, ask it to follow {out}")
        else:
            print(f"flow record {out['id']}: {out['arc']}, {out['length_bucket']}, {out['industry']}")
    elif a.stage == "embed":
        embed.run(a.library, a.url)
    elif a.stage == "package":
        package.run(a.library)
    elif a.stage == "exclusions":
        dropped, blanks = dedupe.report(a.library)
        print(f"{dropped} duplicate slide(s), {blanks} blank slide(s): see {a.library}/work/dedupe-report.txt and "
              "blank-report.txt")
    elif a.stage in ("layout-prep", "mockup"):
        slides = a.slides and {n.strip().zfill(2) for n in a.slides.split(",")}
        if a.stage == "mockup":
            print("\n".join(map(str, mockup.run(a.deck_id, a.library, slides))))
        else:
            out = label_prep.run(a.deck_id, a.library, slides, layouts_only=True)
            print(f"Draw each layout: in Claude Code, ask it to follow every {out}/slide-NN.prompt.txt")


if __name__ == "__main__":
    main()
