# Target-aware clue synthesis (engine revision 6)

Revision 6 improves the construction of custom grids and Autopilot questions.
It retains a planted solution and the existing four-form automatic clue pool.
The final grid must still have a unique complete arrangement, independently
checked by enumeration and Z3. Every displayed answer or true/false claim also
receives an exact minimum-support certificate.

## Construction

1. Build and prune the legacy greedy clue set as a baseline.
2. Evaluate up to eight eligible question/claim targets, always including the
   legacy selection. Fix true/false polarity before optimizing support.
3. Repair eligible targets within a shared work budget. An alternative arrangement
   requires selecting a clue that excludes it. A short answer proof prohibits
   keeping all of its optional clues together in the next proposal.
4. Prune completed proposals and rank certified properties: requested gates,
   answer support, fewer added clues, then clue-kind diversity.
5. Render the selected clues, question and claim together, then independently
   verify the complete grid and actual displayed answer.

Authored clues remain mandatory and ordered. Explicit question targets and
answer groups cannot change. An authored-only shortcut makes that target
unrepairable; other eligible targets can still receive their share of search.
Deduction-only requests require propagation to finish without assumed cases.

The shared limits are 48 candidate evaluations, 2,000 branch nodes and 100,000
support subsets per design. Autopilot compares six designs. Final independent
support certification has its own existing 100,000-subset limit. Automatic
preferences do not increase the baseline clue-count bound; an explicit minimum
can raise it enough to accommodate the requested count. Exhausted search can
return a certified baseline only if the requested gates actually hold.

Saved revisions 1–5 retain their original code paths and random-number usage.
Search telemetry records logical work, not elapsed time, for deterministic replay.

## Bounded comparison, 2026-10-10

The comparison uses seeds 0, 6 and 11 on four fixtures: three positions/two groups,
the same grid with an authored clue, three positions/three groups, and four
positions/two groups. All twelve pairs share the planted solution, requested
question and available clue pool.

| Measurement | Revision 5 | Revision 6 |
|---|---:|---:|
| Independently verified outputs | 12/12 | 12/12 |
| Mean exact answer support | 2.67 | 3.33 |
| Mean displayed clue count | 3.92 | 3.67 |
| Questions requiring at least three clues | 7/12 | 12/12 |
| Distinct structures | 12 | 12 |
| Instrumented median generation time | 33 ms | 44 ms |

Six paired outputs increased support; none decreased it. Three used fewer clues
without losing support. The seed-6 Ada/colour case changes from four clues with
two-clue answer support to three clues with three-clue answer support. A tiny
exhaustive oracle independently searches all 1,771 relational three-clue subsets.

A separate run gave each revision the same 0.25-second generation allowance per
fixture/starting seed. Revision 5 completed 114 verified generations before the
deadlines; revision 6 completed 99. Mean best support was 3.50 versus 3.67, and
mean clue count in those best designs was 3.75 versus 3.67. Revisions alternated
order after warm-up; validation and best-result selection were outside the
allowance. In-flight overruns were excluded and recorded separately.

These small local measurements demonstrate the quality/throughput tradeoff;
they do not establish universal gains, global optimality or human difficulty.
Large grids still pay for exhaustive world masks and independent certification.

Reproduce the corpus and equal-time comparison from the repository root:

```powershell
./.venv/Scripts/python.exe -B tools/benchmark_clue_synthesis.py --candidate-revision 6 --cases three-by-two,three-by-two-authored,three-by-three,four-by-two --seconds-per-case 0.25 --oracle
```

The synthesis regression tests independently enumerate support, protect authored
rules and targets, cover both truth values and zero/partial work budgets, freeze
revision-5 output hashes, and reject altered saved proofs during replay.
