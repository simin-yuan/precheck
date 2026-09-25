"""End-to-end demo. Prints a full transcript -- every line below is real
output from this repository, not an illustration.

    python demo.py

It shows the failure mode the tool exists for: a check passes, and then turns
out it could not have failed.
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from precheck import core        # noqa: E402
from precheck.cli import main    # noqa: E402

SRC = os.path.join(HERE, "examples", "agent-claims")


def step(root, *args):
    print("\n$ precheck " + " ".join(args))
    rc = main(["--root", root] + list(args))
    print("  (exit %s)" % rc)
    return rc


def run():
    root = tempfile.mkdtemp(prefix="precheck-demo-")
    shutil.copytree(SRC, root, dirs_exist_ok=True)
    os.makedirs(core.store_dir(root), exist_ok=True)
    shutil.copy(os.path.join(root, "commitments.json"),
                core.commitments_path(root))

    print("demo root: <tmp>/%s" % os.path.basename(root))
    print("the agent's claim is in commitments.json; the work it judges is "
          "config.json.")

    step(root, "register")
    step(root, "settle")
    step(root, "audit")
    step(root, "verify")
    return 0


if __name__ == "__main__":
    sys.exit(run())
