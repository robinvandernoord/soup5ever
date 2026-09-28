"""Reader for html5lib-tests tree-construction ``.dat`` files."""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).parent / "data" / "html5lib-tests" / "tree-construction"
HEADINGS = {
    "#data", "#errors", "#new-errors", "#document-fragment",
    "#script-off", "#script-on", "#document",
}


@dataclass
class Case:
    id: str
    data: str
    document: str
    fragment: str | None
    scripting: bool | None

    @property
    def applicable(self) -> bool:
        """BS4 parses whole documents with scripting disabled."""
        return self.fragment is None and self.scripting is not True


def load(path: pathlib.Path) -> list[Case]:
    cases: list[Case] = []
    sections: dict[str, list[str]] = {}
    current: str | None = None

    def flush() -> None:
        if "#data" not in sections:
            return
        doc = sections.get("#document", [])
        while doc and doc[-1] == "":
            doc.pop()
        cases.append(
            Case(
                id=f"{path.stem}:{len(cases)}",
                data="\n".join(sections["#data"]),
                document="\n".join(doc),
                fragment=("\n".join(sections["#document-fragment"]).strip()
                          if "#document-fragment" in sections else None),
                scripting=(True if "#script-on" in sections
                           else False if "#script-off" in sections else None),
            )
        )

    with path.open(encoding="utf-8", newline="") as f:
        text = f.read()
    for line in text.split("\n"):
        if line in HEADINGS:
            if line == "#data":
                flush()
                sections = {}
            current = line
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    flush()
    return cases


def all_cases() -> list[Case]:
    if not ROOT.exists():
        return []
    return [case for path in sorted(ROOT.glob("*.dat")) for case in load(path)]
