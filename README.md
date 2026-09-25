<p align="center">
  <img src="assets/banner.svg" alt="precheck" width="880">
</p>

<h1 align="center">precheck</h1>

<p align="center"><b>Make an agent prove its claims with checks it was not allowed to write.</b></p>

<p align="center">
  <a href="https://github.com/simin-yuan/precheck/actions/workflows/tests.yml"><img alt="tests" src="https://github.com/simin-yuan/precheck/actions/workflows/tests.yml/badge.svg"></a>
  <img alt="license" src="https://img.shields.io/badge/license-MIT-blue">
  <img alt="python" src="https://img.shields.io/badge/python-3.8%2B-blue">
  <img alt="dependencies" src="https://img.shields.io/badge/dependencies-0-brightgreen">
  <img alt="network" src="https://img.shields.io/badge/network-none-lightgrey">
</p>

---

An agent finishes and reports success. Today you can believe it, or re-read
every diff yourself. `precheck` is a third option.

It does two things a test runner does not:

1. **It freezes the check before the run.** The acceptance check is written and
   hash-locked *before* the work happens, so the actor cannot tailor the test to
   whatever it ended up producing. Edit the check afterwards and every verdict
   after that point is void — provably, not by convention.
2. **It asks whether the check could have failed at all.** After a check passes,
   `precheck` mutates the artifact it was judging and runs it again. A check that
   still passes on broken input was never evidence for anything.

## What that looks like

Every line below is real output from `python demo.py` in this repository. (The
trailing `(exit N)` annotations it prints, and its temp-directory line, are
omitted here.)

```
$ precheck register
froze 1 commitment(s) at seq=1  sha256=e2d4561aa9f0

$ precheck settle
PASS  the deployment config is valid and safe to ship

1/1 passed  (seq=2)

$ precheck audit
ran 4 mutation(s) across the declared artefacts

2 check/mutation pair(s) survived -- these prove nothing yet:
  ? C1  [blank-value on config.json]
      replicas: 3 -> 0
      the check still exited 0
  ? C1  [flip-number on config.json]
      "replicas": 3, -> "replicas": 10,
      the check still exited 0

This is a question list, not a bug list. Some survivors are legitimate.

$ precheck verify
. commitments unchanged since seq=1 (e2d4561aa9f0)

3 entries; chain consistent
```

The check caught a broken file. It did not catch a config that would take
production down: `replicas: 3` became `0` and the check still said yes. That is
the failure mode this tool exists for.

## Install

```
pip install precheck
```

Zero runtime dependencies, standard library only, no network calls.
Python 3.8+.

## Use it

Three commands you run in order, and one anyone can run afterwards.

```
precheck init          # writes .precheck/commitments.json
#   ... edit it: state the claim, the check, and the artifacts it is about
precheck register      # freeze it -- do this BEFORE the work runs
#   ... whatever produces the artifact runs here ...
precheck settle        # run the frozen checks, record PASS / FAIL / TIMEOUT
precheck audit         # mutate the artifacts; find checks that cannot fail
precheck verify        # walk the hash chain; detect edited history
```

`settle` exits `2` on any failure. `audit --strict` exits `3` if a check survived
a mutation. `verify` exits `1` if the chain is broken. All three drop straight
into CI.

### The commitments file

```json
{
  "version": 1,
  "commitments": [
    {
      "id": "C1",
      "statement": "the deployment config is valid and safe to ship",
      "check": "python check_config.py",
      "artifacts": ["config.json"]
    }
  ]
}
```

`check` is any shell command whose exit code decides the claim. `artifacts` are
the files that claim is about — the audit mutates those.

### Mutations

`drop-line` · `blank-value` · `flip-number` · `truncate`

Deterministic given `--seed`, so a survivor is reproducible and can be argued
about. Binary files are never mutated.

## Why not just use pytest?

`pytest` asks *is the code right?* `precheck` asks *is your proof right?* They
are different questions, and the second one currently has no tooling:

- `pytest` has no opinion on who wrote the test, or when. `precheck` refuses a
  check that was written after the result it judges.
- `pytest` cannot tell you that a passing test would also pass on a broken
  file. `precheck` mutates and re-runs to find out.
- `pytest` results live in your terminal. `precheck` records them in a chain a
  third party can verify without trusting you.

You keep using pytest. You point `precheck` at it.

## How the tamper-evidence works

Each ledger entry is canonical JSON (sorted keys, fixed separators), and holds
`prev` — the previous entry's sha256 — plus its own hash. Editing any byte of any
entry re-hashes to something different, and deleting an entry breaks the link
after it. `verify` re-walks the whole file and reports:

| finding | meaning |
|---|---|
| `HASH_MISMATCH` | an entry's body was edited |
| `BROKEN_LINK` | an entry was deleted, or its predecessor was replaced |
| `SEQ_GAP` | entries were removed from the middle |
| `COMMITMENTS_MODIFIED` | the check was rewritten after it was frozen |
| `NOT_REGISTERED` | checks were never frozen at all |

Commit `.precheck/` with your code. That is the point — a reader can re-run
`precheck verify` on your repository and see for themselves.

## Limits — read this before you trust it

- **A surviving mutation is a question, not a bug.** The mutated line may be
  genuinely irrelevant to the claim. `precheck` will not tell you which; a human
  decides.
- **Surviving every mutation is not proof that a check is vacuous.** The
  mutations are a fixed sample of four. A check can be useless in ways this
  sample never touches.
- **The chain proves history was not edited after the fact. It does not prove
  the first entry was honest.** Whoever writes the first `register` entry can
  still write a weak check. Pre-registration raises the cost of gaming the
  result; it does not make gaming impossible.
- **A weak artifact list defeats it.** If you declare no artifacts, there is
  nothing to mutate and `audit` will honestly report that it examined nothing.
  Declare the files the claim is actually about.
- **Exit codes only.** `precheck` has no idea what your check *means*. A check
  that prints a lie and exits 0 is a check that passes.

## Status

Alpha. 19 unit tests over the chain, the freeze, and the audit; a runnable
end-to-end demo; no dependencies. The audit's mutation set is deliberately small
and readable — adding mutations that you cannot explain to a reader would make
the output less trustworthy, not more.

## License

MIT © 2026 Simin Yuan

