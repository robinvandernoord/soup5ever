"""Benchmark BeautifulSoup(markup, "html5ever") against BeautifulSoup(markup, "html5lib").

    uv pip install -e .[dev]
    python benchmarks/run.py                 # all documents
    python benchmarks/run.py --quick         # fewer repetitions
    python benchmarks/run.py --json out.json

What is timed is the call users make, `BeautifulSoup(markup, parser)`,
on a `str` that is already in memory: no file I/O, imports or interpreter
start-up. For each document and parser the call is repeated in several
rounds (after one warm-up call); the reported figure is the median of the
per-call round times, with the minimum alongside. The garbage collector
stays enabled, as in real use, but is run between rounds so one round's
garbage isn't billed to the next.

A breakdown shows where the time goes:

* html5ever: Rust parsing alone (`soup5ever._soup5ever._parse_only`) vs
  the full call, whose remainder is creating BeautifulSoup objects;
* html5lib: html5lib's own parser with its native `etree` tree builder vs
  the full BeautifulSoup call, whose remainder is BS4's html5lib adapter.
"""

from __future__ import annotations

import argparse
import gc
import itertools
import json
import platform
import statistics
import sys
import threading
import time
import warnings

import bs4
import html5lib
from bs4 import BeautifulSoup
from tabulate import tabulate

import soup5ever
from documents import BENCHMARKS  # benchmarks/documents.py, next to this script
from soup5ever import _soup5ever

warnings.simplefilter("ignore")


def measure(fn, budget: float, rounds: int) -> tuple[float, float]:
    """(median, min) seconds per call."""
    fn()  # warm-up
    start = time.perf_counter()
    fn()
    once = max(time.perf_counter() - start, 1e-6)
    number = max(1, int(budget / rounds / once))
    per_call = []
    for _ in range(rounds):
        gc.collect()
        start = time.perf_counter()
        for _ in range(number):
            fn()
        per_call.append((time.perf_counter() - start) / number)
    return statistics.median(per_call), min(per_call)


def fmt(seconds: float) -> str:
    if seconds >= 1:
        return f"{seconds:.2f} s"
    if seconds >= 1e-3:
        return f"{seconds * 1e3:.1f} ms"
    return f"{seconds * 1e6:.0f} µs"


class Spinner:
    """Show the current step on one self-overwriting stderr line."""

    FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self) -> None:
        self.text = ""
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._enabled = sys.stderr.isatty()

    def __enter__(self) -> "Spinner":
        if self._enabled:
            self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self._stop.set()
        if self._enabled:
            self._thread.join()
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()

    def _spin(self) -> None:
        for frame in itertools.cycle(self.FRAMES):
            if self._stop.wait(0.1):
                return
            sys.stderr.write(f"\r\033[K{frame} {self.text}")
            sys.stderr.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--json")
    parser.add_argument("names", nargs="*", default=list(BENCHMARKS))
    args = parser.parse_args()
    budget, rounds = (1.5, 3) if args.quick else (6.0, 7)

    env = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "machine": platform.machine(),
        "beautifulsoup4": bs4.__version__,
        "html5lib": html5lib.__version__,
        "soup5ever": soup5ever.__version__,
    }
    results = []
    with Spinner() as spinner:
        for n, name in enumerate(args.names, 1):
            description, factory = BENCHMARKS[name]
            markup = factory()
            steps = {
                "html5lib": (lambda m=markup: BeautifulSoup(m, "html5lib"), budget),
                "html5ever": (lambda m=markup: BeautifulSoup(m, "html5ever"), budget),
                "Rust parse only": (lambda m=markup: _soup5ever._parse_only(m), budget / 3),
                "html5lib parser only": (lambda m=markup: html5lib.parse(m, treebuilder="etree"), budget),
            }
            timings = {}
            for step, (fn, step_budget) in steps.items():
                spinner.text = f"[{n}/{len(args.names)}] {name}: {step}"
                timings[step] = measure(fn, step_budget, rounds)
            results.append(
                {
                    "name": name,
                    "description": description,
                    "bytes": len(markup.encode()),
                    "nodes": _soup5ever._parse_only(markup),
                    "html5lib": timings["html5lib"][0],
                    "html5lib_min": timings["html5lib"][1],
                    "html5ever": timings["html5ever"][0],
                    "html5ever_min": timings["html5ever"][1],
                    "rust_parse": timings["Rust parse only"][0],
                    "html5lib_parser_only": timings["html5lib parser only"][0],
                }
            )

    print(", ".join(f"{k} {v}" for k, v in env.items()))
    rows = [
        [
            row["description"],
            f"{row['bytes'] / 1024:.0f} KiB",
            f"{row['nodes']:,}",
            fmt(row["html5lib"]),
            fmt(row["html5ever"]),
            f"{row['html5lib'] / row['html5ever']:.1f}x",
            f"{fmt(row['rust_parse'])} ({row['rust_parse'] / row['html5ever']:.0%})",
            f"{fmt(row['html5lib_parser_only'])} ({row['html5lib_parser_only'] / row['html5lib']:.0%})",
        ]
        for row in results
    ]
    headers = ["document", "size", "nodes", "html5lib", "html5ever", "speedup", "Rust parse", "html5lib parser"]
    print(tabulate(rows, headers=headers, tablefmt="rounded_outline", colalign=["left"] + ["right"] * 7))
    if args.json:
        with open(args.json, "w") as f:
            json.dump({"environment": env, "results": results}, f, indent=2)


if __name__ == "__main__":
    main()
