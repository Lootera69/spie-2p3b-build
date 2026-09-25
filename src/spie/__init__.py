"""Symbolic Puzzle Invention Engine (spie).

A non-LLM engine for representing formal logic puzzles, proving them solvable and
unique with a formal solver (Z3), and emitting machine-verifiable certificates.

This package is Vertical Slice 1: representation + proof loop only. Generation,
quality-diversity search, and the semantic concept pipeline come in later phases.
"""

__version__ = "0.1.0"
