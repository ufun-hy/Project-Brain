#!/usr/bin/env python3
"""Inspect task state and record explicit review decisions."""
import argparse, json
from task_status import StatusStore, is_stale, transition

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument("--runtime-dir")
    sub=p.add_subparsers(dest="cmd",required=True); sub.add_parser("list")
    show=sub.add_parser("show"); show.add_argument("task_id")
    review=sub.add_parser("review"); review.add_argument("task_id"); review.add_argument("decision",choices=["accepted","needs_changes"]); review.add_argument("--reason",default="")
    args=p.parse_args(); store=StatusStore(__import__('pathlib').Path(args.runtime_dir) if args.runtime_dir else None)
    if args.cmd=="list":
        for r in store.list(): print(f"{r['task_id']}\t{r['project']}\t{r['state']}{' (STALE)' if is_stale(r) else ''}\t{r['title']}")
    elif args.cmd=="show": print(json.dumps(store.load(args.task_id),ensure_ascii=False,indent=2))
    else:
        r=store.load(args.task_id); transition(r,args.decision,f"Review decision: {args.decision}",evidence_summary=args.reason or r.get("evidence_summary","")); store.save(r); print(f"{args.task_id}: {args.decision}")
    return 0
if __name__=="__main__": raise SystemExit(main())
