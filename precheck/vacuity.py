"""Vacuity audit -- a check that cannot fail proves nothing.

Settle answers "did the check pass?". This module answers the harder
question: "could it have failed at all?"

For each declared artifact we apply a small, deterministic mutation
(drop a line, blank a value, change a number, truncate a file), re-run the
check, and restore the file byte-for-byte. A check that still passes on
mutated input did not distinguish good from broken.

Findings here are QUESTIONS, not accusations. A surviving mutation is often
legitimate: the mutated line may be irrelevant to that particular claim.
The tool reports what it saw and leaves the judgement to a human -- it never
labels a check "useless" on its own.
"""
import json
import os
import random
import re

MUTATIONS = ("drop-line", "blank-value", "flip-number", "truncate")

_FIELD = re.compile(r"^(\s*[\w.\-]+\s*[:=]\s*)(.+)$", re.M)
_STRING = re.compile(r'"[^"\n]*"')
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])")


def decode(data: bytes):
    """Text of a file, or None if it is not text (we never mutate binary)."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _blank_like(value):
    """Neuter a scalar: empty, zero, false -- but keep its type."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return 0
    if isinstance(value, str):
        return ""
    if isinstance(value, list):
        return []
    if isinstance(value, dict):
        return {}
    return None


def _pick_json_scalar(obj, rng, path=()):
    """Choose one leaf of a JSON document, deterministically."""
    leaves = []

    def walk(node, cur):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, (dict, list)):
                    walk(v, cur + (k,))
                else:
                    leaves.append((cur, k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                if isinstance(v, (dict, list)):
                    walk(v, cur + (i,))
                else:
                    leaves.append((cur, i))

    walk(obj, ())
    if not leaves:
        return None
    parent_path, key = rng.choice(leaves)
    parent = obj
    for step in parent_path:
        parent = parent[step]
    return parent, key


def mutate(kind: str, text: str, rng: random.Random):
    """Apply one mutation.

    Returns (mutated_text, detail) or (None, None) if not applicable.
    `detail` is the human-readable change, e.g. "replicas: 3 -> 0" -- it is the
    whole point of the audit, because it is what a reader can act on.
    """
    lines = text.split("\n")
    filled = [i for i, l in enumerate(lines) if l.strip()]

    if kind == "drop-line":
        if not filled:
            return None, None
        i = rng.choice(filled)
        detail = "dropped line %d: %s" % (i + 1, lines[i].strip()[:60])
        del lines[i]
        return "\n".join(lines), detail

    if kind == "truncate":
        if len(filled) < 2:
            return None, None
        keep = max(1, len(lines) // 2)
        return ("\n".join(lines[:keep]) + "\n",
                "truncated to the first %d of %d lines" % (keep, len(lines)))

    if kind == "blank-value":
        try:
            obj = json.loads(text)
        except ValueError:
            obj = None
        if isinstance(obj, (dict, list)):
            target = _pick_json_scalar(obj, rng)
            if target is None:
                return None, None
            parent, key = target
            old = parent[key]
            parent[key] = _blank_like(old)
            return (json.dumps(obj, ensure_ascii=False, indent=2) + "\n",
                    "%s: %r -> %r" % (key, old, parent[key]))
        hits = list(_FIELD.finditer(text))
        if hits:
            h = rng.choice(hits)
            return (text[:h.start(2)] + '""' + text[h.end(2):],
                    "%s: %r -> \"\"" % (h.group(1).strip(), h.group(2)[:40]))
        hits = list(_STRING.finditer(text))
        if hits:
            h = rng.choice(hits)
            return (text[:h.start()] + '""' + text[h.end():],
                    "%s -> \"\"" % h.group(0)[:40])
        return None, None

    if kind == "flip-number":
        hits = list(_NUMBER.finditer(text))
        if not hits:
            return None, None
        h = rng.choice(hits)
        raw = h.group(0)
        try:
            value = float(raw) if "." in raw else int(raw)
        except ValueError:
            return None, None
        new = value + (1 if value == 0 else (7 if value > 0 else -7))
        new_text = text[:h.start()] + str(new) + text[h.end():]
        start = text.rfind("\n", 0, h.start()) + 1
        end = text.find("\n", h.start())
        if end == -1:
            end = len(text)
        delta = len(str(new)) - len(raw)
        return (new_text,
                "%s -> %s" % (text[start:end].strip()[:60],
                              new_text[start:end + delta].strip()[:60]))

    return None, None


def audit(root, commitments, mutations=MUTATIONS, seed=0, timeout=600,
          runner=None, on_event=None):
    """Mutate each declared artifact, re-run each check, restore, report.

    A check that exits 0 on mutated input is recorded as ESCAPED: we could
    not make it say no, so it is not yet evidence for the claim.
    """
    if runner is None:
        from .runtime import run_check as runner

    escaped = []
    examined = 0
    skipped = []

    for c in commitments.get("commitments", []):
        cid = c.get("id") or c.get("statement", "?")[:24]
        for art in c.get("artifacts", []):
            path = os.path.join(root, art)
            if not os.path.isfile(path):
                skipped.append({"id": cid, "artifact": art,
                                "why": "artifact not found"})
                continue
            with open(path, "rb") as f:
                original = f.read()
            text = decode(original)
            if text is None:
                skipped.append({"id": cid, "artifact": art,
                                "why": "not a text file"})
                continue
            for kind in mutations:
                rng = random.Random("%s|%s|%s|%s" % (seed, cid, art, kind))
                mutated, detail = mutate(kind, text, rng)
                if mutated is None:
                    continue
                examined += 1
                try:
                    with open(path, "w", encoding="utf-8", newline="") as f:
                        f.write(mutated)
                    code, out = runner(c["check"], cwd=root, timeout=timeout)
                finally:
                    with open(path, "wb") as f:
                        f.write(original)
                if on_event:
                    on_event(cid, art, kind, code, detail)
                if code == 0:
                    escaped.append({
                        "id": cid, "artifact": art, "mutation": kind,
                        "detail": detail,
                        "statement": c.get("statement", ""),
                        "check": c["check"],
                        "question": ("%s -- and the check still passed. Either "
                                     "that line does not matter to the claim, "
                                     "or the check would pass on broken input."
                                     % detail),
                    })

    return {"examined": examined, "escaped": escaped, "skipped": skipped}
