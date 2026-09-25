"""precheck command line.

    precheck init                    write a commitments template
    precheck register                freeze the commitments, before the run
    precheck settle                  run the frozen checks, record verdicts
    precheck audit                   mutate artefacts, find checks that can't fail
    precheck verify                  walk the chain, detect edited history
    precheck status                  one-screen summary
"""
import argparse
import json
import os
import sys

from . import core
from .core import PrecheckError
from .runtime import run_check
from .vacuity import MUTATIONS, audit

TEMPLATE = {
    "version": 1,
    "note": ("Write the check BEFORE the work it judges. `check` is a shell "
             "command whose exit code decides the claim; `artifacts` are the "
             "files that claim is about (used by `precheck audit`)."),
    "commitments": [
        {
            "id": "C1",
            "statement": "replace me: what is being claimed",
            "check": "replace me: a command that exits non-zero if it is false",
            "artifacts": ["replace/me.txt"],
        }
    ],
}


def _fail(msg, code=1):
    print(msg, file=sys.stderr)
    return code


def cmd_init(args):
    p = core.commitments_path(args.root)
    if os.path.exists(p):
        return _fail("%s already exists -- not overwriting" % p)
    core.save_commitments(args.root, TEMPLATE)
    print("wrote %s" % p)
    print("edit it, then: precheck register")
    return 0


def cmd_register(args):
    data = core.load_commitments(args.root)
    if not data.get("commitments"):
        return _fail("commitments list is empty -- nothing to freeze")
    h = core.commitments_hash(args.root)
    entry = core.append(args.root, "register",
                        {"commitments_sha256": h,
                         "count": len(data["commitments"]),
                         "ids": [c.get("id") for c in data["commitments"]]})
    print("froze %d commitment(s) at seq=%s  sha256=%s"
          % (len(data["commitments"]), entry["seq"], h[:12]))
    return 0


def cmd_settle(args):
    data = core.load_commitments(args.root)
    results = []
    for c in data.get("commitments", []):
        cid = c.get("id", "?")
        code, out = run_check(c["check"], cwd=args.root, timeout=args.timeout)
        if code is None:
            verdict = "TIMEOUT"
        elif code == 0:
            verdict = "PASS"
        else:
            verdict = "FAIL"
        results.append({"id": cid, "verdict": verdict, "exit": code,
                        "statement": c.get("statement", ""),
                        "check": c["check"]})
        print("%-5s %s" % (verdict, c.get("statement") or cid))
        if verdict != "PASS" and args.verbose:
            print("      $ %s\n      exit=%s\n%s" % (c["check"], code, out.rstrip()))

    entry = core.append(args.root, "settle", {"results": results})
    bad = [r for r in results if r["verdict"] != "PASS"]
    print("\n%d/%d passed  (seq=%s)" % (len(results) - len(bad), len(results),
                                        entry["seq"]))
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if not bad else 2


def cmd_audit(args):
    data = core.load_commitments(args.root)
    kinds = tuple(k.strip() for k in args.mutations.split(",") if k.strip())
    bad = [k for k in kinds if k not in MUTATIONS]
    if bad:
        return _fail("unknown mutation(s): %s (known: %s)"
                     % (", ".join(bad), ", ".join(MUTATIONS)))

    def on_event(cid, art, kind, code, detail):
        if args.verbose:
            print("   %s %s on %s -> exit=%s  [%s]" % (cid, kind, art, code, detail))

    res = audit(args.root, data, mutations=kinds, seed=args.seed,
                timeout=args.timeout, on_event=on_event)
    entry = core.append(args.root, "audit",
                        {"examined": res["examined"],
                         "escaped": res["escaped"],
                         "skipped": res["skipped"],
                         "seed": args.seed,
                         "mutations": list(kinds)})

    print("ran %d mutation(s) across the declared artefacts" % res["examined"])
    for s in res["skipped"]:
        print("  skipped %s (%s: %s)" % (s["artifact"], s["why"], s["id"]))
    if res["escaped"]:
        print("\n%d check/mutation pair(s) survived -- these prove nothing yet:"
              % len(res["escaped"]))
        for e in res["escaped"]:
            print("  ? %s  [%s on %s]" % (e["id"], e["mutation"], e["artifact"]))
            print("      %s" % e.get("detail", ""))
            print("      the check still exited 0")
        print("\nThis is a question list, not a bug list. Some survivors are "
              "legitimate.")
    elif res["examined"] == 0:
        # A run that applied no mutation cannot have caught anything. Saying
        # "every mutation was caught" here would be this project's own bug:
        # a green line produced by a check that was never exercised.
        print("\nNothing was audited: no mutation could be applied, so this "
              "run proves nothing either way.")
        print("Fix the artefacts listed above, then run it again.")
    else:
        print("every mutation was caught by its check.")
    print("(seq=%s)" % entry["seq"])
    if args.strict and (res["escaped"] or res["examined"] == 0):
        return 3
    return 0


def cmd_verify(args):
    res = core.verify(args.root)
    for f in res["findings"]:
        mark = {"high": "!", "info": "."}.get(f["level"], ".")
        print("%s %s" % (mark, f["message"]))
    print("\n%d %s; chain %s"
          % (res["entries"], "entry" if res["entries"] == 1 else "entries",
             "consistent" if res["ok"] else "BROKEN"))
    return 0 if res["ok"] else 1


def cmd_status(args):
    try:
        data = core.load_commitments(args.root)
        n = len(data.get("commitments", []))
    except PrecheckError as e:
        return _fail(str(e))
    entries = core.read_ledger(args.root)
    kinds = {}
    for e in entries:
        kinds[e.get("kind")] = kinds.get(e.get("kind"), 0) + 1
    last = entries[-1] if entries else None
    print("commitments : %d" % n)
    print("ledger      : %d entries %s" % (len(entries), kinds or ""))
    if last:
        print("head        : seq=%s kind=%s %s" % (last.get("seq"),
                                                   last.get("kind"),
                                                   (last.get("hash") or "")[:12]))
    v = core.verify(args.root)
    print("chain       : %s" % ("ok" if v["ok"] else "BROKEN"))
    for f in v["findings"]:
        if f["level"] == "high":
            print("  ! %s" % f["message"])
    return 0 if v["ok"] else 1


def build_parser():
    p = argparse.ArgumentParser(prog="precheck", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=".", help="repository root (default: .)")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="write a commitments template").set_defaults(
        func=cmd_init)
    sub.add_parser("register", help="freeze commitments before the run"
                   ).set_defaults(func=cmd_register)

    s = sub.add_parser("settle", help="run the frozen checks")
    s.add_argument("--timeout", type=int, default=600)
    s.add_argument("--json", action="store_true")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=cmd_settle)

    a = sub.add_parser("audit", help="find checks that cannot fail")
    a.add_argument("--mutations", default=",".join(MUTATIONS))
    a.add_argument("--seed", type=int, default=0)
    a.add_argument("--timeout", type=int, default=600)
    a.add_argument("--strict", action="store_true",
                   help="exit non-zero if any mutation survived (for CI)")
    a.add_argument("-v", "--verbose", action="store_true")
    a.set_defaults(func=cmd_audit)

    sub.add_parser("verify", help="walk the chain").set_defaults(func=cmd_verify)
    sub.add_parser("status", help="summary").set_defaults(func=cmd_status)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except PrecheckError as e:
        return _fail("precheck: %s" % e)


if __name__ == "__main__":
    sys.exit(main())
