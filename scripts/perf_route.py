"""Route a PR to the full `Perf run` job or to a skip (#543, BehindTheMusicTree/github-config#85).

Reads NUL-separated changed paths on stdin (`git diff --no-renames -z --name-only`, so a rename lists both names)
and prints `mode=skip` or `mode=full`. Skip only when every path is explicitly known to have no effect on the perf
suite; anything unknown, an empty input or a mixed diff runs in full. Stdlib only: runs on the runner's system python.
Add a path here only after checking that `perf/`, `scripts/perf_ab.sh` and what they import do not read it.
"""

import sys

SKIP_SUFFIXES = (".md",)
SKIP_FILES = frozenset(
    {
        "LICENSE",
        ".github/release-policy.json",
        ".github/workflows/validate.yml",
        ".github/workflows/catalogue-benchmark.yml",
        ".github/workflows/agent-drift.yml",
        ".github/workflows/org-conformance.yml",
        ".github/workflows/release-tag.yml",
        ".github/workflows/build-and-deploy.yml",
    }
)
# `benchmarks/` is imported by `export_perf_catalogue`, so only its unittest-only subtree is skippable.
SKIP_PREFIXES = (
    "docs/",
    ".agents/",
    ".claude/",
    ".github/skills/",
    "bruno/",
    ".pr-descriptions/",
    "benchmarks/catalogue/tests/",
)


def is_skippable(path: str) -> bool:
    return path in SKIP_FILES or path.endswith(SKIP_SUFFIXES) or path.startswith(SKIP_PREFIXES)


def classify(paths: list[str]) -> tuple[str, list[str]]:
    """Return ("skip" | "full", the paths that forced a full run)."""
    if not paths:
        return "full", []
    offending = [p for p in paths if not is_skippable(p)]
    return ("full" if offending else "skip"), offending


def main() -> None:
    paths = [p for p in sys.stdin.buffer.read().decode("utf-8", "surrogateescape").split("\0") if p]
    mode, offending = classify(paths)
    if mode == "full":
        print(f"perf_route: full run ({'; '.join(offending[:5]) or 'no changed files reported'})", file=sys.stderr)
    print(f"mode={mode}")


if __name__ == "__main__":
    main()
