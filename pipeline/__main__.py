"""python -m pipeline <stage> ...  (run from the repo root; outputs go to ./library/, which is gitignored)."""
import argparse
import sys

from pipeline import build, embed, extract, label_prep, leak_check, package


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m pipeline")
    sub = ap.add_subparsers(dest="stage", required=True)
    p = sub.add_parser("extract", help="render + extract a .pptx; prints the new deck_id")
    p.add_argument("deck")
    p.add_argument("--skip-render", action="store_true", help="no slide PNGs (when LibreOffice/poppler are missing)")
    for name, help_ in (("label-prep", "write labeling worksheets"), ("build", "labels + geometry -> DNA, wireframe"),
                        ("leak-check", "check, write judge worksheet, promote passing records")):
        sub.add_parser(name, help=help_).add_argument("deck_id")
    p = sub.add_parser("embed", help="embed published descriptions via the local Worker")
    p.add_argument("--url", default=f"http://127.0.0.1:{embed.PORT}")
    sub.add_parser("package", help="write records.sql and copy wireframes for deploy")
    for p in sub.choices.values():
        p.add_argument("--library", default="library")
    a = ap.parse_args(argv)

    if a.stage == "extract":
        print(f"deck_id {extract.run(a.deck, a.library, render=not a.skip_render)}")
    elif a.stage == "label-prep":
        work = label_prep.run(a.deck_id, a.library)
        print(f"Label each slide: in Claude Code, ask it to follow every {work}/slide-NN.prompt.txt")
    elif a.stage == "build":
        print("\n".join(build.run(a.deck_id, a.library)))
    elif a.stage == "leak-check":
        report = leak_check.run(a.deck_id, a.library)
        for rid, r in report.items():
            print(rid, f"auto={r['auto']}", f"judge={r['judge']}", *r["problems"], sep="  ")
        if any(r["auto"] != "pass" or r["judge"] != "pass" for r in report.values()):
            print(f"Not published: fix labels and rebuild, or judge in a fresh session (library/judge/{a.deck_id}/JUDGE.txt).")
            sys.exit(1)
    elif a.stage == "embed":
        embed.run(a.library, a.url)
    elif a.stage == "package":
        package.run(a.library)


if __name__ == "__main__":
    main()
