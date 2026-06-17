#!/usr/bin/env python3
"""
Sync myst.yml TOC with DATA 88E lecture and lab notebooks on disk.
Discovers lec/lecNN/*.ipynb and lab/N/labNN/labNN.ipynb, builds the table of
contents in edX course order, and updates myst.yml.
Run from repository root. Exits 0 if no change, 2 on error.
"""
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("PyYAML required: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
MYST_PATH = REPO_ROOT / "myst.yml"

EXIT_SUCCESS = 0
EXIT_ERROR = 2

PART_CONFIG = {
    "1": {
        "title": "Part 1 - Fundamentals of Economics",
        "lectures": ["01", "02", "03"],
        "lab_part": "1",
    },
    "2": {
        "title": "Part 2 - Advanced Concepts in Economics",
        "lectures": ["04", "05", "06"],
        "lab_part": "2",
    },
    "3": {
        "title": "Part 3 - Real-World Applications of Economics",
        "lectures": ["07", "08", "09", "10"],
        "lab_part": "3",
    },
}

LECTURE_TITLES = {
    "00": "Getting Started",
    "01": "Lecture 1 - Demand",
    "02": "Lecture 2 - Supply",
    "03": "Lecture 3 - Taxes, Government Intervention, and Welfare",
    "04": "Lecture 4 - Macroeconomics",
    "05": "Lecture 5 - Utility",
    "06": "Lecture 6 - Inequality and Development",
    "07": "Lecture 7 - Game Theory",
    "08": "Lecture 8 - Econometrics",
    "09": "Lecture 9 - Environmental Economics",
    "10": "Lecture 10 - Finance",
}


def notebook_title(path: Path) -> str:
    """Return the first markdown heading in a notebook, or a filename fallback."""
    try:
        with open(path, encoding="utf-8") as f:
            nb = json.load(f)
        for cell in nb.get("cells", []):
            if cell.get("cell_type") != "markdown":
                continue
            source = cell.get("source", "")
            if isinstance(source, list):
                source = "".join(source)
            for line in source.splitlines():
                stripped = line.strip()
                if stripped.startswith("# "):
                    return stripped[2:].strip()
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    return path.stem.replace("-", " ").replace("_", " ").title()


def rel_path(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")


def notebook_sort_key(path: Path) -> tuple:
    """Sort notebooks by section numbers such as 5.1, 5.2a, 5.2b."""
    title = notebook_title(path)
    match = re.search(
        r"(?:Lecture Notebook|Lab)\s+(\d+(?:\.\d+[a-z]?)?)",
        title,
        re.IGNORECASE,
    )
    if match:
        parts = re.findall(r"\d+|[a-z]", match.group(1), re.IGNORECASE)
        key = []
        for part in parts:
            key.append(int(part) if part.isdigit() else ord(part.lower()) - ord("a"))
        return tuple(key)
    numbers = tuple(int(n) for n in re.findall(r"\d+", path.stem))
    return numbers if numbers else (999,), path.stem


def find_lec_notebooks(lec_num: str) -> list[dict]:
    """Find all notebooks under lec/lecNN/, sorted by section number."""
    base = REPO_ROOT / "lec" / f"lec{lec_num}"
    if not base.is_dir():
        return []
    entries = []
    for path in sorted(base.glob("*.ipynb"), key=notebook_sort_key):
        entries.append({"title": notebook_title(path), "file": rel_path(path)})
    return entries


def find_part_labs(part: str) -> list[dict]:
    """Find all labNN/labNN.ipynb under lab/part/, sorted by NN."""
    base = REPO_ROOT / "lab" / part
    if not base.is_dir():
        return []
    pattern = re.compile(r"^lab(\d+)$")
    entries = []
    for path in sorted(base.iterdir()):
        if not path.is_dir():
            continue
        match = pattern.match(path.name)
        if not match:
            continue
        nb = path / f"{path.name}.ipynb"
        if nb.is_file():
            entries.append({"title": notebook_title(nb), "file": rel_path(nb)})
    entries.sort(key=lambda e: int(re.search(r"lab(\d+)", e["file"]).group(1)))
    return entries


def build_toc() -> list[dict]:
    toc = []

    intro = REPO_ROOT / "intro.md"
    if intro.exists():
        toc.append({"file": "intro.md"})

    getting_started = find_lec_notebooks("00")
    if getting_started:
        if len(getting_started) == 1:
            entry = getting_started[0].copy()
            entry["title"] = LECTURE_TITLES["00"]
            toc.append(entry)
        else:
            toc.append(
                {"title": LECTURE_TITLES["00"], "children": getting_started}
            )

    for part in sorted(PART_CONFIG):
        config = PART_CONFIG[part]
        children = []

        for lec_num in config["lectures"]:
            notebooks = find_lec_notebooks(lec_num)
            if not notebooks:
                continue
            if len(notebooks) == 1:
                entry = notebooks[0].copy()
                entry["title"] = LECTURE_TITLES.get(lec_num, entry["title"])
                children.append(entry)
            else:
                children.append(
                    {
                        "title": LECTURE_TITLES.get(lec_num, f"Lecture {lec_num}"),
                        "children": notebooks,
                    }
                )

        labs = find_part_labs(config["lab_part"])
        if labs:
            children.append({"title": "Labs", "children": labs})

        if children:
            toc.append({"title": config["title"], "children": children})

    return toc


def main() -> int:
    if not MYST_PATH.is_file():
        print(f"Error: {MYST_PATH} not found", file=sys.stderr)
        return EXIT_ERROR

    toc = build_toc()

    try:
        with open(MYST_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        print(f"Error: invalid YAML in {MYST_PATH}: {e}", file=sys.stderr)
        return EXIT_ERROR

    if data is None:
        data = {}
    if "project" not in data:
        data["project"] = {}

    old_toc = data["project"].get("toc", [])
    if old_toc == toc:
        return EXIT_SUCCESS

    data["project"]["toc"] = toc
    with open(MYST_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    return EXIT_SUCCESS


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(EXIT_ERROR)
