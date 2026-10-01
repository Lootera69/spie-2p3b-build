"""Connected crossword construction and independent reconstruction checks."""

from __future__ import annotations

import random
from collections import deque
from functools import lru_cache

from .content import LEXICONS

BOARD_SIZES = tuple(range(5, 16))


def recommend_size(
    vocabulary: list[tuple[str, str]], count: int,
    required_words: list[str] | None = None,
    required_groups: list[list[str]] | None = None,
) -> dict:
    """Find a compact checked layout without treating all related words as mandatory."""
    return _recommend(tuple(vocabulary), count, tuple(required_words or ()),
                      tuple(tuple(group) for group in (required_groups or ())))


@lru_cache(maxsize=64)
def _recommend(vocabulary, count, required_words, required_groups) -> dict:
    options = []
    recommended = None
    for size in BOARD_SIZES:
        error = size_issue(vocabulary, count, size, required_words, required_groups)
        options.append({"id": size, "label": f"{size}×{size}", "available": not error,
                        "reason": error or "Word lengths fit; crossings still need checking."})
        if error or recommended is not None:
            continue
        try:
            data, _ = construct("logic", count, random.Random(0), list(vocabulary),
                                [list(g) for g in required_groups], list(required_words),
                                board_size=size)
        except ValueError:
            continue
        recommended = size
        lengths = [len(c["answer"]) for c in data["clues"]]
    reason = (f"A checked sample fits {count} entries of {min(lengths)}–{max(lengths)} letters "
              f"on {recommended}×{recommended}. Larger boards are also welcome; "
              "they keep the same entry count with more blank space."
              if recommended else
              "No connected sample found within 5×5–15×15. Try fewer entries, "
              "different words or another variation; a size can still be selected manually.")
    return {"recommended": recommended, "options": options,
            "entry_count": count, "reason": reason}


def size_issue(vocabulary, count, size, required_words=(), required_groups=()) -> str:
    eligible = {word for word, _ in vocabulary if len(word) <= size}
    too_long = [word for word in required_words if len(word) > size]
    if too_long:
        return f"Required word {too_long[0]} has {len(too_long[0])} letters; choose a larger board."
    if not set(required_words) <= eligible:
        return "A required word is missing from the available vocabulary."
    if any(not eligible.intersection(group) for group in required_groups):
        return f"A selected topic has no usable word that fits {size}×{size}."
    if len(eligible) < count:
        return f"Only {len(eligible)} words fit {size}×{size}; this level needs {count}."
    return ""


def validate_grid(data: dict) -> dict:
    """Reconstruct every across/down run, number, crossing and connected cell."""
    size, grid, clues = data.get("size"), data.get("grid"), data.get("clues")
    if type(size) is not int or not 3 <= size <= 19:
        raise ValueError("Crossword size must be between 3 and 19")
    if (
        not isinstance(grid, list)
        or len(grid) != size
        or any(not isinstance(row, list) or len(row) != size for row in grid)
    ):
        raise ValueError("Crossword grid must be square")
    cells = {}
    for r, row in enumerate(grid):
        for c, value in enumerate(row):
            if value is not None:
                if not isinstance(value, str) or len(value) != 1 or not "A" <= value <= "Z":
                    raise ValueError("Grid cells must be uppercase letters or null")
                cells[r, c] = value
    if not cells or not isinstance(clues, list) or not 3 <= len(clues) <= 12:
        raise ValueError("Expected at least three crossword clues")
    runs = {}
    starts = {}
    for r, c in sorted(cells):
        for direction, dr, dc in (("across", 0, 1), ("down", 1, 0)):
            if (r - dr, c - dc) in cells or (r + dr, c + dc) not in cells:
                continue
            if (r, c) not in starts:
                starts[r, c] = len(starts) + 1
            letters = []
            rr, cc = r, c
            while (rr, cc) in cells:
                letters.append(cells[rr, cc])
                rr, cc = rr + dr, cc + dc
            runs[r, c, direction] = "".join(letters)
    claimed, covered, answers = set(), set(), set()
    for clue in clues:
        if not isinstance(clue, dict) or set(clue) != {
            "number",
            "clue",
            "answer",
            "startRow",
            "startCol",
            "direction",
        }:
            raise ValueError("Invalid crossword clue fields")
        r, c = clue["startRow"], clue["startCol"]
        if (
            type(r) is not int
            or type(c) is not int
            or type(clue["number"]) is not int
            or clue["direction"] not in ("across", "down")
        ):
            raise ValueError("Invalid clue position")
        key = r, c, clue["direction"]
        if (
            key in claimed
            or runs.get(key) != clue["answer"]
            or starts.get((r, c)) != clue["number"]
        ):
            raise ValueError("Clue does not match its numbered grid run")
        if (
            not isinstance(clue["clue"], str)
            or not clue["clue"].strip()
            or clue["answer"] in answers
        ):
            raise ValueError("Empty clue or repeated answer")
        answers.add(clue["answer"])
        claimed.add(key)
        for i in range(len(clue["answer"])):
            covered.add((r + (i if key[2] == "down" else 0), c + (i if key[2] == "across" else 0)))
    if claimed != set(runs) or covered != set(cells):
        raise ValueError("Unclued run or uncovered grid cell")
    reached, queue = set(), deque([next(iter(cells))])
    while queue:
        cell = queue.popleft()
        if cell in reached:
            continue
        reached.add(cell)
        r, c = cell
        queue.extend(
            p
            for p in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1))
            if p in cells and p not in reached
        )
    if reached != set(cells):
        raise ValueError("Disconnected crossword")
    return {
        "entries": len(clues),
        "filled_cells": len(cells),
        "connected": True,
        "all_runs_clued": True,
        "numbering_matches": True,
    }


def construct(
    category: str, count: int, rng: random.Random,
    vocabulary: list[tuple[str, str]] | None = None,
    required_groups: list[list[str]] | None = None,
    required_words: list[str] | None = None,
    board_size: int | None = None,
) -> tuple[dict, dict]:
    if board_size is not None and (type(board_size) is not int or board_size not in BOARD_SIZES):
        raise ValueError("Crossword board size must be between 5 and 15")
    size = 19 if board_size is None else board_size
    vocabulary = list(LEXICONS[category] if vocabulary is None else vocabulary)
    if board_size is not None:
        error = size_issue(vocabulary, count, board_size, required_words or (),
                           required_groups or ())
        if error:
            raise ValueError(error)
        vocabulary = [entry for entry in vocabulary if len(entry[0]) <= board_size]
        eligible = {word for word, _ in vocabulary}
        required_groups = [[word for word in group if word in eligible]
                           for group in (required_groups or ())]
    if len(vocabulary) < count:
        raise ValueError(f"This topic needs at least {count} words for this crossword difficulty")
    required_groups = required_groups or []
    required_words = required_words or []
    if len(required_groups) > count or len(set(required_words)) > count:
        raise ValueError("Choose a larger crossword to include all your topics")
    original_vocabulary = list(vocabulary)
    for attempt in range(200 if board_size is not None else 100):
        if attempt == 100:
            # Retry the recommendation's deterministic search at the SAME size.
            # A compact checked sample must remain usable for other variation seeds.
            rng = random.Random(0)
            vocabulary = list(original_vocabulary)
        rng.shuffle(vocabulary)
        if required_groups or required_words:
            priority = set(required_words)
            for group in required_groups:
                if not priority.intersection(group):
                    priority.add(rng.choice(group))
            vocabulary.sort(key=lambda entry: entry[0] not in priority)
        cells: dict[tuple[int, int], str] = {}
        directions: dict[tuple[int, int], set[str]] = {}
        entries = []
        for word, clue in vocabulary:
            proposals = []
            if not cells:
                proposals.append((size // 2 if board_size is None else rng.randrange(size),
                                  (size - len(word)) // 2, "across"))
            else:
                for (r, c), letter in cells.items():
                    for i, char in enumerate(word):
                        if char != letter:
                            continue
                        for direction in ("across", "down"):
                            if direction not in directions[r, c]:
                                proposals.append(
                                    (
                                        r - (i if direction == "down" else 0),
                                        c - (i if direction == "across" else 0),
                                        direction,
                                    )
                                )
                rng.shuffle(proposals)
            for r, c, direction in proposals:
                dr, dc = (0, 1) if direction == "across" else (1, 0)
                positions = [(r + i * dr, c + i * dc) for i in range(len(word))]
                if any(not 0 <= rr < size or not 0 <= cc < size for rr, cc in positions):
                    continue
                if (r - dr, c - dc) in cells or (r + len(word) * dr, c + len(word) * dc) in cells:
                    continue
                valid = True
                for position, char in zip(positions, word, strict=True):
                    rr, cc = position
                    if position in cells:
                        if cells[position] != char or direction in directions[position]:
                            valid = False
                    elif (rr - dc, cc - dr) in cells or (rr + dc, cc + dr) in cells:
                        valid = False
                if not valid:
                    continue
                for position, char in zip(positions, word, strict=True):
                    cells[position] = char
                    directions.setdefault(position, set()).add(direction)
                entries.append(
                    {
                        "answer": word,
                        "clue": clue,
                        "startRow": r,
                        "startCol": c,
                        "direction": direction,
                    }
                )
                break
            if len(entries) == count:
                placed = {e["answer"] for e in entries}
                if (not set(required_words) <= placed
                        or any(not placed.intersection(group) for group in required_groups)):
                    break
                min_r, min_c = min(r for r, _ in cells), min(c for _, c in cells)
                side = max(max(r for r, _ in cells) - min_r, max(c for _, c in cells) - min_c) + 1
                output_size = size if board_size is not None else side
                row_offset = -min_r + ((output_size - side) // 2 if board_size else 0)
                col_offset = -min_c + ((output_size - side) // 2 if board_size else 0)
                grid = [[None for _ in range(output_size)] for _ in range(output_size)]
                for (r, c), letter in cells.items():
                    grid[r + row_offset][c + col_offset] = letter
                starts = sorted({(e["startRow"], e["startCol"]) for e in entries})
                for e in entries:
                    e["number"] = starts.index((e["startRow"], e["startCol"])) + 1
                    e["startRow"] += row_offset
                    e["startCol"] += col_offset
                entries.sort(key=lambda e: (e["number"], e["direction"]))
                data = {"size": output_size, "grid": grid, "clues": entries}
                return data, validate_grid(data)
    if board_size is not None:
        raise ValueError(f"Could not connect all required words on {board_size}×{board_size}. "
                         "Try a larger board, fewer entries or another variation. "
                         "The selected size was not changed.")
    if required_groups:
        raise ValueError("Could not connect words from every topic. Try a higher difficulty, "
                         "another variation, or different topics.")
    raise ValueError("Could not construct a connected crossword; try another seed")
