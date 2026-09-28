"""Benchmark BeautifulSoup(markup, "html5ever") against BeautifulSoup(markup, "html5lib").

    python -m benchmarks.run                 # all documents
    python -m benchmarks.run --quick         # fewer repetitions
    python -m benchmarks.run --json out.json

What is timed is the call users make, ``BeautifulSoup(markup, parser)``,
on a ``str`` that is already in memory: no file I/O, imports or interpreter
start-up. For each document and parser the call is repeated in several
rounds (after one warm-up call); the reported figure is the median of the
per-call round times, with the minimum alongside. The garbage collector
stays enabled, as in real use, but is run between rounds so one round's
garbage isn't billed to the next.

A breakdown shows where the time goes:

* html5ever: Rust parsing alone (``soup5ever._soup5ever._parse_only``) vs
  the full call, whose remainder is creating BeautifulSoup objects;
* html5lib: html5lib's own parser with its native ``etree`` tree builder vs
  the full BeautifulSoup call, whose remainder is BS4's html5lib adapter.
"""

from __future__ import annotations

import argparse
import gc
import json
import platform
import statistics
import sys
import time
import warnings

import bs4
import html5lib
from bs4 import BeautifulSoup

import soup5ever
from soup5ever import _soup5ever

from .documents import BENCHMARKS

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
    print(" ".join(f"{k}={v}" for k, v in env.items()))
    print()
    header = (
        "| document | size | nodes | html5lib | html5ever | speedup "
        "| html5ever: Rust parse | html5lib: parser only |"
    )
    print(header)
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    results = []
    for name in args.names:
        description, factory = BENCHMARKS[name]
        markup = factory()
        nodes = _soup5ever._parse_only(markup)
        lib, lib_min = measure(lambda m=markup: BeautifulSoup(m, "html5lib"), budget, rounds)
        ever, ever_min = measure(lambda m=markup: BeautifulSoup(m, "html5ever"), budget, rounds)
        rust, _ = measure(lambda m=markup: _soup5ever._parse_only(m), budget / 3, rounds)
        native, _ = measure(lambda m=markup: html5lib.parse(m, treebuilder="etree"), budget, rounds)
        row = {
            "name": name,
            "description": description,
            "bytes": len(markup.encode()),
            "nodes": nodes,
            "html5lib": lib,
            "html5lib_min": lib_min,
            "html5ever": ever,
            "html5ever_min": ever_min,
            "rust_parse": rust,
            "html5lib_parser_only": native,
        }
        results.append(row)
        print(
            f"| {name} ({description}) | {row['bytes'] / 1024:.0f} KiB | {nodes:,} "
            f"| {fmt(lib)} | {fmt(ever)} | **{lib / ever:.1f}x** "
            f"| {fmt(rust)} ({rust / ever:.0%}) | {fmt(native)} ({native / lib:.0%}) |",
            flush=True,
        )
    if args.json:
        with open(args.json, "w") as f:
            json.dump({"environment": env, "results": results}, f, indent=2)


if __name__ == "__main__":
    main()
