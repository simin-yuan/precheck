"""The check the agent wrote for itself, and declared as its own proof.

It answers "is this file parseable JSON?" and stops there. It never looks at
a single value -- so it is exactly the kind of check that passes on a config
that would take production down.
"""
import json
import sys

try:
    json.load(open("config.json", encoding="utf-8"))
except Exception as exc:  # noqa: BLE001
    print("invalid config: %s" % exc)
    sys.exit(1)

print("config parses -- nothing else was examined")
sys.exit(0)
