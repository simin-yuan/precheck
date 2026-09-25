"""precheck core: commitments, the hash chain, and verification.

The rule this tool exists to enforce:

    The check must exist BEFORE the work it judges, and the actor under
    judgement must not be able to edit it afterwards.

So: the commitment file is frozen by hash at registration time, and every
later verdict is appended to a hash-chained ledger. Editing either one is
detectable by a third party who has nothing but the repo.
"""
import hashlib, json, os, time

DIRNAME = ".precheck"
COMMITMENTS = "commitments.json"
LEDGER = "ledger.jsonl"
MARKER = b"# precheck ledger v1\n"


class PrecheckError(Exception):
    pass


def canonical(obj) -> bytes:
    """Deterministic bytes for hashing. Key order and spacing fixed."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def store_dir(root: str = ".") -> str:
    return os.path.join(root, DIRNAME)


def commitments_path(root: str = ".") -> str:
    return os.path.join(store_dir(root), COMMITMENTS)


def ledger_path(root: str = ".") -> str:
    return os.path.join(store_dir(root), LEDGER)


def load_commitments(root: str = ".") -> dict:
    p = commitments_path(root)
    if not os.path.exists(p):
        raise PrecheckError(
            "no commitments file at %s -- run `precheck init` then edit it" % p)
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "commitments" not in data:
        raise PrecheckError("commitments file must be an object with a "
                            "'commitments' list")
    return data


def save_commitments(root: str, data: dict) -> None:
    os.makedirs(store_dir(root), exist_ok=True)
    with open(commitments_path(root), "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=False)
        f.write("\n")


def commitments_hash(root: str = ".") -> str:
    """Hash of the commitments file on disk, right now."""
    return sha256_file(commitments_path(root))


def read_ledger(root: str = ".") -> list:
    p = ledger_path(root)
    if not os.path.exists(p):
        return []
    out = []
    with open(p, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                out.append(json.loads(line))
            except ValueError as e:
                raise PrecheckError("ledger line %d is not valid JSON: %s"
                                    % (lineno, e))
    return out


def _entry_hash(entry: dict) -> str:
    body = {k: v for k, v in entry.items() if k != "hash"}
    return sha256_bytes(canonical(body))


def append(root: str, kind: str, payload: dict) -> dict:
    """Append one hash-chained entry to the ledger. Returns the entry."""
    os.makedirs(store_dir(root), exist_ok=True)
    entries = read_ledger(root)
    entry = {
        "seq": len(entries) + 1,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "kind": kind,
        "prev": entries[-1]["hash"] if entries else None,
    }
    entry.update(payload)
    entry["hash"] = _entry_hash(entry)
    p = ledger_path(root)
    new = not os.path.exists(p)
    with open(p, "a", encoding="utf-8", newline="\n") as f:
        if new:
            f.write(MARKER.decode())
        f.write(json.dumps(entry, sort_keys=True, ensure_ascii=False) + "\n")
    return entry


def verify(root: str = ".") -> dict:
    """Walk the chain and compare the frozen commitments to the live file.

    Returns {"ok": bool, "entries": int, "findings": [...]}.
    A finding is a question for a human, not a verdict: this function only
    reports what it can check mechanically.
    """
    findings = []

    def add(level, code, msg):
        findings.append({"level": level, "code": code, "message": msg})

    entries = read_ledger(root)
    if not entries:
        add("high", "NO_LEDGER",
            "no ledger yet -- nothing has been registered or settled")
        return {"ok": False, "entries": 0, "findings": findings}

    for i, e in enumerate(entries):
        if e.get("seq") != i + 1:
            add("high", "SEQ_GAP",
                "entry %d has seq=%r, expected %d" % (i + 1, e.get("seq"), i + 1))
        if e.get("hash") != _entry_hash(e):
            add("high", "HASH_MISMATCH",
                "entry %d does not hash to its own recorded hash "
                "(the entry body was edited)" % (i + 1))
        want = entries[i - 1]["hash"] if i else None
        if e.get("prev") != want:
            add("high", "BROKEN_LINK",
                "entry %d points at prev=%r but the previous entry's hash is %r"
                % (i + 1, e.get("prev"), want))

    regs = [e for e in entries if e.get("kind") == "register"]
    if not regs:
        add("high", "NOT_REGISTERED",
            "no register entry -- checks were never frozen before the run")
    else:
        frozen = regs[-1].get("commitments_sha256")
        live = commitments_hash(root)
        if frozen != live:
            add("high", "COMMITMENTS_MODIFIED",
                "commitments file hash is %s but %s was frozen at seq=%s; "
                "every verdict recorded after that point is void"
                % (live[:12], (frozen or "?")[:12], regs[-1].get("seq")))
        else:
            add("info", "COMMITMENTS_FROZEN",
                "commitments unchanged since seq=%s (%s)"
                % (regs[-1].get("seq"), (frozen or "")[:12]))

    ok = not any(f["level"] == "high" for f in findings)
    return {"ok": ok, "entries": len(entries), "findings": findings}
