"""hydrabrain CLI — a gbrain-style memory CLI backed by HydraDB.

Commands (mirroring gbrain):
  hydrabrain status                 show tenant + memory count
  hydrabrain capture "<text>"       ingest a thought / consumed content
  hydrabrain ingest <file...>       ingest text/markdown files
  hydrabrain sync <dir|glob...>     bulk, incremental ingest (skips unchanged files)
  hydrabrain read <url...>          ingest a web article / YouTube transcript
  hydrabrain search "<query>"       hybrid vector+graph+BM25 retrieval
  hydrabrain think  "<query>"       synthesized, cited answer + gap analysis
  hydrabrain graph  <source_id>     explore the knowledge graph
  hydrabrain serve                  run the MCP server (stdio)
  hydrabrain bench [...]            run the HydraDB-vs-gbrain-stack benchmark
"""

from __future__ import annotations

import argparse
import json
import sys


def _engine(args):
    from .engine import BrainEngine

    return BrainEngine(tenant_id=args.tenant)


def cmd_status(args):
    print(json.dumps(_engine(args).status(), indent=2))


def cmd_capture(args):
    eng = _engine(args)
    res = eng.capture(args.text, title=args.title or "")
    print("captured.", json.dumps(res)[:300])


def cmd_ingest(args):
    eng = _engine(args)
    for path in args.files:
        eng.ingest_file(path)
        print(f"ingested: {path}")


def cmd_read(args):
    eng = _engine(args)
    for url in args.urls:
        try:
            res = eng.ingest_url(url)
            print(f"read [{res['kind']}] {res['chars']} chars — {res['title'][:80]}")
        except Exception as e:
            print(f"failed: {url} — {type(e).__name__}: {str(e)[:120]}")


def cmd_sync(args):
    eng = _engine(args)
    exts = [e if e.startswith(".") else f".{e}" for e in args.ext] if args.ext else None

    def _progress(done, total, path, action):
        if action in {"ingested", "would-ingest"} or action.startswith("error"):
            import os
            print(f"  [{done}/{total}] {action:13} {os.path.basename(path)}")

    res = eng.sync(args.paths, recursive=not args.no_recursive, force=args.force,
                   dry_run=args.dry_run, extensions=exts, on_progress=_progress)
    tag = "DRY RUN — " if args.dry_run else ""
    print(f"\n{tag}sync done: {json.dumps(res.summary())}")


def cmd_search(args):
    chunks = _engine(args).search(args.query, k=args.k, graph=not args.no_graph)
    if not chunks:
        print("(no results)")
        return
    for i, c in enumerate(chunks, 1):
        snippet = c.text.strip().replace("\n", " ")
        print(f"[{i}] (score={c.score:.3f}) {snippet[:200]}")


def cmd_think(args):
    ans = _engine(args).think(args.query, k=args.k, graph=not args.no_graph)
    print(ans.render())


def cmd_graph(args):
    print(json.dumps(_engine(args).graph(args.source_id), indent=2)[:4000])


def cmd_serve(args):
    from .mcp_server import main as serve_main

    serve_main(tenant_id=args.tenant)


def cmd_bench(args):
    # Delegate to the benchmark package.
    from bench.run_bench import main as bench_main

    bench_main(args.bench_args)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hydrabrain", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--tenant", default=None, help="HydraDB tenant id")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("status"); sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("capture")
    sp.add_argument("text"); sp.add_argument("--title", default="")
    sp.set_defaults(func=cmd_capture)

    sp = sub.add_parser("ingest")
    sp.add_argument("files", nargs="+"); sp.set_defaults(func=cmd_ingest)

    sp = sub.add_parser("read", help="ingest a web page / YouTube transcript by URL")
    sp.add_argument("urls", nargs="+", help="article or YouTube URLs")
    sp.set_defaults(func=cmd_read)

    sp = sub.add_parser("sync", help="bulk, incremental ingest of dirs/files/globs")
    sp.add_argument("paths", nargs="+", help="directories, files, or globs")
    sp.add_argument("--ext", nargs="*", default=None, help="file extensions to include (default: md/txt/rst/org/…)")
    sp.add_argument("--no-recursive", action="store_true", help="do not descend into subdirectories")
    sp.add_argument("--force", action="store_true", help="ignore the manifest; re-ingest everything")
    sp.add_argument("--dry-run", action="store_true", help="show what would be ingested without writing")
    sp.set_defaults(func=cmd_sync)

    sp = sub.add_parser("search")
    sp.add_argument("query"); sp.add_argument("-k", type=int, default=5)
    sp.add_argument("--no-graph", action="store_true")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("think")
    sp.add_argument("query"); sp.add_argument("-k", type=int, default=6)
    sp.add_argument("--no-graph", action="store_true")
    sp.set_defaults(func=cmd_think)

    sp = sub.add_parser("graph")
    sp.add_argument("source_id"); sp.set_defaults(func=cmd_graph)

    sp = sub.add_parser("serve"); sp.set_defaults(func=cmd_serve)

    sp = sub.add_parser("bench")
    sp.add_argument("bench_args", nargs=argparse.REMAINDER)
    sp.set_defaults(func=cmd_bench)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
