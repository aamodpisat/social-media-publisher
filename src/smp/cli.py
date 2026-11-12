from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Social Media Publisher")
    sub = parser.add_subparsers(dest="cmd", required=True)

    gen = sub.add_parser("generate", help="Create this week's draft batch from templates")
    gen.add_argument("--force", action="store_true", help="Generate even if the week already has drafts")

    sub.add_parser("publish-due", help="Publish approved drafts if today is a posting day")
    publish_one = sub.add_parser("publish-one", help="Upload and publish one new media file")
    publish_one.add_argument("--media", help="Exact eligible media path selected by the local agent")
    publish_one.add_argument("--caption", help="Caption prepared by the local agent")
    sub.add_parser("next-media", help="Print the next eligible media path and type without publishing")
    serve = sub.add_parser("serve", help="Run the approval UI")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)

    if args.cmd == "generate":
        from smp.generator.run import generate_week

        items = generate_week(force=args.force)
        print(f"Batch items: {len(items)}")
        for item in items:
            print(f"  {item.status:18} {item.content_type:6} {item.title}")
        return 0

    if args.cmd == "publish-due":
        from smp.scheduler.run import publish_due

        results = publish_due()
        if not results:
            print("No publish run (not a posting day, or nothing approved).")
            return 0
        for item in results:
            print(f"  {item.status:18} {item.content_type:6} {item.title} {item.error}")
        return 0

    if args.cmd == "publish-one":
        from smp.scheduler.auto import publish_one_new

        item = publish_one_new(
            media_path=Path(args.media).expanduser() if args.media else None,
            caption=args.caption or "",
        )
        if item is None:
            print("No eligible new media found.")
            return 0
        print(f"{item.status}: {item.content_type} — {item.title}")
        if item.error:
            print(item.error)
        return 0 if item.status == "published" else 1

    if args.cmd == "next-media":
        from smp.scheduler.auto import next_media

        item = next_media()
        if item is None:
            print("No eligible media.")
            return 0
        path, content_type = item
        print(f"{content_type}\t{path}")
        return 0

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("smp.web:app", host=args.host, port=args.port, reload=False)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
