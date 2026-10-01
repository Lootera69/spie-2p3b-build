"""Item 3, Phase C3 — the generated SPIE decision model (offline, frozen, **never hand-edited**).

GENERATED FILE — produced by ``tools/policy_train`` from a corpus SPIE harvests from its own search,
and checked in as a frozen artifact. Regenerate it with the recipe in :data:`BUILD_PARAMS`; never
edit it by hand: :data:`ARTIFACT_HASH` pins the exact weights the offline fit produced, and
``tests/test_decision_model.py`` recomputes that hash.

What this is, and why it is thesis-safe:

* **A propose-only decision model.** The values below are the per-operator ridge stats of a disjoint
  LinUCB bandit (Li et al. 2010): for each mutation operator, ``A_MAT[op] = ridge*I + Σ x·xᵀ`` and
  ``B_VEC[op] = Σ survived·x`` over the training triples, where ``x`` is the parent elite's
  :func:`spie.mapelites._context_features` vector and ``survived`` is the child's outcome under the
  unchanged ``validate -> verify -> certify`` gate. :class:`spie.decision.FrozenProposer` loads them
  and proposes ``argmax_op predict(op, context)`` — it only chooses *what operator to try*.
* **The solvers remain the sole judge.** Every child the proposer suggests still clears the formal
  gate before it can occupy a cell; the fitted weights never touch acceptance, and at runtime the
  model never learns online (``FrozenProposer.reward`` credits nothing back to these weights).
* **Plain primitives, no ``spie`` import.** The weights are ``float`` / ``list`` / ``dict`` only, so
  this module imports nothing from :mod:`spie`: there is no import cycle, and the artifact is a pure
  data literal whose content hash the shipped tests re-derive.
* **Offline and reproducible.** The corpus is generated once, deterministically, from the pinned
  grid in :data:`BUILD_PARAMS`; importing this module touches no network, no API and no model, so
  the engine's LLM-free, byte-reproducible thesis is untouched.
"""

from __future__ import annotations

import hashlib

MODEL_VERSION = "1"
"""The trainer revision that produced these weights."""

CORPUS_SHA256 = "sha256:80d28165e5ed1902a8ba13c5ad1c18244aff68bb19745a5d9abab1d61086a531"
"""sha256 of the canonical training corpus — provenance. Empty only while the artifact is empty
(no corpus has been fitted yet)."""

BUILD_PARAMS: dict[str, object] = {
    'alpha': 1.0,
    'context_features': "spie.mapelites._context_features",
    'corpus_rows': 600,
    'dim': 7,
    'integer_seeds': [0, 1, 2],
    'iterations': 50,
    'operators': [
                     "add_decoy_action",
                     "add_reset_action",
                     "add_resource_budget",
                     "compose_actions",
                     "couple_variables",
                     "delay_effect",
                     "flip_persistence",
                     "hide_variable",
                     "invert_goal",
                     "make_observation_costly",
                     "remove_redundant_clue",
                     "require_invariant",
                     "reveal_variable",
                     "reverse_edge",
                     "synchronize_subsystems",
                     "transfer_property",
                 ],
    'ridge': 1.0,
    'seed_populations': [
                            ["move", "which_door", "combination_lock"],
                            ["hidden", "lockkey", "pressure"],
                            ["two_agents", "push_block", "synchronize"],
                            ["transform", "resource", "irreversible"],
                        ],
    'size_max': 600,
    'size_min': 600,
}
"""The exact grid and hyper-parameters the fit ran with, so the artifact can be regenerated.
Empty only while the artifact is empty."""

DIM = 7
"""The context-vector width (:data:`spie.mapelites._CONTEXT_DIM`); each weight row/vector is DIM
long. The features are defined solely by ``spie.mapelites._context_features``, shared by train and
inference so there is no feature skew."""

ALPHA = 1.0
"""The LinUCB exploration weight the model was fitted under (reported; the frozen proposer exploits
the mean and does not add an exploration bonus)."""

RIDGE = 1.0
"""The ridge prior ``A0 = ridge*I`` — keeps every per-operator matrix symmetric positive-definite
(hence invertible) and every untried operator tied at the prior."""

A_MAT: dict[str, list[list[float]]] = {
    'add_decoy_action': [
                            [45.0, 10.25, 0.929513, 34.574723, 39.714284, 8.571429, 7.428571],
                            [10.25, 5.4375, 0.175314, 6.69979, 8.178571, 2.892857, 2.035714],
                            [0.929513, 0.175314, 1.035184, 0.675683, 0.763262, 0.184843, 0.174968],
                            [
                                34.574723,
                                6.69979,
                                0.675683,
                                30.059381,
                                33.021819,
                                5.794504,
                                5.354944,
                            ],
                            [
                                39.714284,
                                8.178571,
                                0.763262,
                                33.021819,
                                38.734692,
                                6.77551,
                                6.204081,
                            ],
                            [8.571429, 2.892857, 0.184843, 5.794504, 6.77551, 3.367347, 1.714286],
                            [7.428571, 2.035714, 0.174968, 5.354944, 6.204081, 1.714286, 2.387755],
                        ],
    'add_reset_action': [
                            [32.0, 5.5, 0.837181, 25.432433, 28.857142, 5.571429, 5.0],
                            [5.5, 3.125, 0.10667, 3.690775, 4.464285, 1.5, 1.071429],
                            [0.837181, 0.10667, 1.034345, 0.675824, 0.754055, 0.145625, 0.140687],
                            [
                                25.432433,
                                3.690775,
                                0.675824,
                                22.923572,
                                24.655981,
                                4.060834,
                                3.841054,
                            ],
                            [
                                28.857142,
                                4.464285,
                                0.754055,
                                24.655981,
                                28.867346,
                                4.673469,
                                4.387755,
                            ],
                            [5.571429, 1.5, 0.145625, 4.060834, 4.673469, 2.367347, 1.040816],
                            [5.0, 1.071429, 0.140687, 3.841054, 4.387755, 1.040816, 1.877551],
                        ],
    'add_resource_budget': [
                               [32.0, 5.75, 0.739357, 25.263637, 28.357142, 6.0, 5.142857],
                               [5.75, 4.1875, 0.070487, 3.395496, 4.339285, 1.857143, 1.214286],
                               [
                                   0.739357,
                                   0.070487,
                                   1.030004,
                                   0.593619,
                                   0.651911,
                                   0.135353,
                                   0.127947,
                               ],
                               [
                                   25.263637,
                                   3.395496,
                                   0.593619,
                                   22.908423,
                                   24.294878,
                                   4.201555,
                                   3.871885,
                               ],
                               [
                                   28.357142,
                                   4.339285,
                                   0.651911,
                                   24.294878,
                                   28.117346,
                                   4.816326,
                                   4.387755,
                               ],
                               [6.0, 1.857143, 0.135353, 4.201555, 4.816326, 2.673469, 1.183673],
                               [
                                   5.142857,
                                   1.214286,
                                   0.127947,
                                   3.871885,
                                   4.387755,
                                   1.183673,
                                   1.938776,
                               ],
                           ],
    'compose_actions': [
                           [39.0, 10.0, 0.808848, 29.260204, 33.785713, 8.0, 6.571429],
                           [10.0, 5.75, 0.163206, 6.266932, 7.696428, 3.142857, 2.071429],
                           [0.808848, 0.163206, 1.029868, 0.595862, 0.675519, 0.161998, 0.149654],
                           [
                               29.260204,
                               6.266932,
                               0.595862,
                               25.288363,
                               27.710911,
                               5.151143,
                               4.601693,
                           ],
                           [
                               33.785713,
                               7.696428,
                               0.675519,
                               27.710911,
                               32.801019,
                               6.081632,
                               5.367347,
                           ],
                           [8.0, 3.142857, 0.161998, 5.151143, 6.081632, 3.489796, 1.673469],
                           [6.571429, 2.071429, 0.149654, 4.601693, 5.367347, 1.673469, 2.265306],
                       ],
    'couple_variables': [
                            [22.0, 5.5, 0.51804, 16.320911, 18.928571, 4.428571, 3.571429],
                            [5.5, 3.625, 0.082181, 3.442532, 4.232143, 1.785714, 1.142857],
                            [0.51804, 0.082181, 1.02029, 0.417547, 0.467836, 0.094426, 0.08702],
                            [
                                16.320911,
                                3.442532,
                                0.417547,
                                14.556736,
                                15.54807,
                                2.875043,
                                2.545373,
                            ],
                            [
                                18.928571,
                                4.232143,
                                0.467836,
                                15.54807,
                                18.933673,
                                3.408163,
                                2.979592,
                            ],
                            [4.428571, 1.785714, 0.094426, 2.875043, 3.408163, 2.408163, 0.918367],
                            [3.571429, 1.142857, 0.08702, 2.545373, 2.979592, 0.918367, 1.673469],
                        ],
    'delay_effect': [
                        [46.0, 9.75, 1.06974, 35.060805, 40.142855, 8.857143, 7.714286],
                        [9.75, 5.5625, 0.165515, 6.047918, 7.535714, 2.857143, 2.0],
                        [1.06974, 0.165515, 1.043205, 0.771061, 0.866246, 0.214186, 0.204311],
                        [35.060805, 6.047918, 0.771061, 30.451092, 33.311983, 5.912924, 5.473364],
                        [40.142855, 7.535714, 0.866246, 33.311983, 38.918366, 6.897959, 6.32653],
                        [8.857143, 2.857143, 0.214186, 5.912924, 6.897959, 3.44898, 1.795918],
                        [7.714286, 2.0, 0.204311, 5.473364, 6.32653, 1.795918, 2.469388],
                    ],
    'flip_persistence': [
                            [44.0, 10.75, 1.034256, 33.634729, 39.214284, 8.0, 7.142857],
                            [10.75, 5.0625, 0.199426, 7.497926, 9.053571, 2.642857, 2.0],
                            [1.034256, 0.199426, 1.042285, 0.767511, 0.872325, 0.196103, 0.188696],
                            [
                                33.634729,
                                7.497926,
                                0.767511,
                                28.919923,
                                32.274133,
                                5.495385,
                                5.165715,
                            ],
                            [
                                39.214284,
                                9.053571,
                                0.872325,
                                32.274133,
                                38.484692,
                                6.489795,
                                6.061224,
                            ],
                            [8.0, 2.642857, 0.196103, 5.495385, 6.489795, 3.040816, 1.55102],
                            [7.142857, 2.0, 0.188696, 5.165715, 6.061224, 1.55102, 2.306122],
                        ],
    'hide_variable': [
                         [52.0, 12.25, 1.289186, 37.522774, 43.428568, 11.0, 9.285714],
                         [12.25, 6.5625, 0.252761, 7.163742, 8.857142, 3.964286, 2.678571],
                         [1.289186, 0.252761, 1.055046, 0.840337, 0.965324, 0.280874, 0.266061],
                         [37.522774, 7.163742, 0.840337, 31.485421, 34.801582, 6.741243, 6.081903],
                         [43.428568, 8.857142, 0.965324, 34.801582, 40.969385, 7.979591, 7.122448],
                         [11.0, 3.964286, 0.280874, 6.741243, 7.979591, 4.367347, 2.387755],
                         [9.285714, 2.678571, 0.266061, 6.081903, 7.122448, 2.387755, 2.897959],
                     ],
    'invert_goal': [
                       [28.0, 5.75, 0.711359, 20.543989, 23.285713, 6.0, 4.857143],
                       [5.75, 4.3125, 0.091105, 2.964834, 3.821428, 2.214286, 1.357143],
                       [0.711359, 0.091105, 1.029998, 0.521553, 0.58235, 0.144368, 0.134492],
                       [20.543989, 2.964834, 0.521553, 18.202044, 19.187004, 3.741134, 3.301574],
                       [23.285713, 3.821428, 0.58235, 19.187004, 22.551019, 4.367347, 3.795918],
                       [6.0, 2.214286, 0.144368, 3.741134, 4.367347, 2.959184, 1.306122],
                       [4.857143, 1.357143, 0.134492, 3.301574, 3.795918, 1.306122, 1.979592],
                   ],
    'make_observation_costly': [
                                   [30.0, 5.0, 0.765784, 22.754911, 25.714284, 5.571429, 5.0],
                                   [5.0, 3.125, 0.112714, 2.975607, 3.678571, 1.5, 1.071429],
                                   [
                                       0.765784,
                                       0.112714,
                                       1.032254,
                                       0.540276,
                                       0.608174,
                                       0.154047,
                                       0.149109,
                                   ],
                                   [
                                       22.754911,
                                       2.975607,
                                       0.540276,
                                       20.33564,
                                       21.586622,
                                       3.77629,
                                       3.55651,
                                   ],
                                   [
                                       25.714284,
                                       3.678571,
                                       0.608174,
                                       21.586622,
                                       25.234692,
                                       4.346938,
                                       4.061224,
                                   ],
                                   [5.571429, 1.5, 0.154047, 3.77629, 4.346938, 2.44898, 1.122449],
                                   [5.0, 1.071429, 0.149109, 3.55651, 4.061224, 1.122449, 1.959184],
                               ],
    'remove_redundant_clue': [
                                 [34.0, 5.0, 0.808096, 28.352448, 31.5, 6.0, 5.142857],
                                 [5.0, 3.75, 0.04936, 3.090442, 3.875, 1.678571, 1.035714],
                                 [
                                     0.808096,
                                     0.04936,
                                     1.029642,
                                     0.730725,
                                     0.795134,
                                     0.126552,
                                     0.119146,
                                 ],
                                 [
                                     28.352448,
                                     3.090442,
                                     0.730725,
                                     26.210701,
                                     27.775526,
                                     4.544855,
                                     4.215185,
                                 ],
                                 [31.5, 3.875, 0.795134, 27.775526, 31.75, 5.142857, 4.714286],
                                 [6.0, 1.678571, 0.126552, 4.544855, 5.142857, 2.591837, 1.102041],
                                 [
                                     5.142857,
                                     1.035714,
                                     0.119146,
                                     4.215185,
                                     4.714286,
                                     1.102041,
                                     1.857143,
                                 ],
                             ],
    'require_invariant': [
                             [57.0, 12.5, 1.289333, 43.959138, 50.571426, 10.571429, 9.428571],
                             [12.5, 6.0, 0.239206, 8.342431, 10.142857, 3.285714, 2.428571],
                             [1.289333, 0.239206, 1.051726, 0.92491, 1.048597, 0.254867, 0.244992],
                             [
                                 43.959138,
                                 8.342431,
                                 0.92491,
                                 37.896769,
                                 42.014397,
                                 7.233094,
                                 6.793534,
                             ],
                             [
                                 50.571426,
                                 10.142857,
                                 1.048597,
                                 42.014397,
                                 49.102039,
                                 8.448979,
                                 7.87755,
                             ],
                             [
                                 10.571429,
                                 3.285714,
                                 0.254867,
                                 7.233094,
                                 8.448979,
                                 3.734694,
                                 2.081633,
                             ],
                             [9.428571, 2.428571, 0.244992, 6.793534, 7.87755, 2.081633, 2.755102],
                         ],
    'reveal_variable': [
                           [38.0, 7.0, 0.993895, 29.349948, 33.214284, 7.142857, 6.285714],
                           [7.0, 3.875, 0.149033, 4.386271, 5.303571, 2.107143, 1.464286],
                           [0.993895, 0.149033, 1.042204, 0.743493, 0.831964, 0.190337, 0.182931],
                           [
                               29.349948,
                               4.386271,
                               0.743493,
                               26.001553,
                               27.989352,
                               4.883273,
                               4.553603,
                           ],
                           [
                               33.214284,
                               5.303571,
                               0.831964,
                               27.989352,
                               32.484692,
                               5.632653,
                               5.204081,
                           ],
                           [7.142857, 2.107143, 0.190337, 4.883273, 5.632653, 2.918367, 1.428571],
                           [6.285714, 1.464286, 0.182931, 4.553603, 5.204081, 1.428571, 2.183673],
                       ],
    'reverse_edge': [
                        [34.0, 7.0, 0.907679, 25.611853, 29.642855, 5.857143, 5.571429],
                        [7.0, 3.25, 0.165959, 4.915284, 5.910714, 1.5, 1.285714],
                        [0.907679, 0.165959, 1.040357, 0.62942, 0.717147, 0.179925, 0.177456],
                        [25.611853, 4.915284, 0.62942, 22.307229, 24.439953, 4.068569, 3.958679],
                        [29.642855, 5.910714, 0.717147, 24.439953, 29.168366, 4.755101, 4.612244],
                        [5.857143, 1.5, 0.179925, 4.068569, 4.755101, 2.285714, 1.122449],
                        [5.571429, 1.285714, 0.177456, 3.958679, 4.612244, 1.122449, 2.040816],
                    ],
    'synchronize_subsystems': [
                                  [
                                      52.0,
                                      12.25,
                                      1.017366,
                                      40.456507,
                                      46.285713,
                                      10.285714,
                                      8.571429,
                                  ],
                                  [12.25, 6.6875, 0.187086, 7.862211, 9.571428, 3.785714, 2.5],
                                  [
                                      1.017366,
                                      0.187086,
                                      1.034542,
                                      0.785469,
                                      0.879716,
                                      0.195489,
                                      0.180676,
                                  ],
                                  [
                                      40.456507,
                                      7.862211,
                                      0.785469,
                                      35.199391,
                                      38.714907,
                                      6.91545,
                                      6.25611,
                                  ],
                                  [
                                      46.285713,
                                      9.571428,
                                      0.879716,
                                      38.714907,
                                      45.051019,
                                      8.081632,
                                      7.224489,
                                  ],
                                  [
                                      10.285714,
                                      3.785714,
                                      0.195489,
                                      6.91545,
                                      8.081632,
                                      4.061224,
                                      2.081633,
                                  ],
                                  [8.571429, 2.5, 0.180676, 6.25611, 7.224489, 2.081633, 2.591837],
                              ],
    'transfer_property': [
                             [31.0, 8.0, 0.674528, 22.785113, 26.285713, 6.428571, 5.285714],
                             [8.0, 4.875, 0.128187, 4.942864, 6.071428, 2.535714, 1.678571],
                             [0.674528, 0.128187, 1.026884, 0.484805, 0.545519, 0.139106, 0.129231],
                             [
                                 22.785113,
                                 4.942864,
                                 0.484805,
                                 19.804902,
                                 21.428128,
                                 4.061295,
                                 3.621735,
                             ],
                             [
                                 26.285713,
                                 6.071428,
                                 0.545519,
                                 21.428128,
                                 25.551019,
                                 4.795918,
                                 4.224489,
                             ],
                             [6.428571, 2.535714, 0.139106, 4.061295, 4.795918, 3.020408, 1.367347],
                             [5.285714, 1.678571, 0.129231, 3.621735, 4.224489, 1.367347, 2.040816],
                         ],
}
"""Per-operator ridge matrix ``A = ridge*I + Σ x·xᵀ`` (6-dp-rounded), keyed by operator
``__name__``, in sorted-key order."""

B_VEC: dict[str, list[float]] = {
    'add_decoy_action': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    'add_reset_action': [3.0, 0.75, 0.048603, 2.4, 3.0, 0.428571, 0.428571],
    'add_resource_budget': [10.0, 1.75, 0.171194, 8.725442, 10.0, 1.428571, 1.428571],
    'compose_actions': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    'couple_variables': [3.0, 0.5, 0.121143, 2.587413, 3.0, 0.428571, 0.428571],
    'delay_effect': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    'flip_persistence': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    'hide_variable': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    'invert_goal': [5.0, 0.0, 0.08106, 4.675325, 5.0, 0.714286, 0.714286],
    'make_observation_costly': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    'remove_redundant_clue': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    'require_invariant': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    'reveal_variable': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    'reverse_edge': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    'synchronize_subsystems': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    'transfer_property': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
}
"""Per-operator ridge vector ``b = Σ survived·x`` (6-dp-rounded), keyed by operator ``__name__``,
in sorted-key order."""

ARTIFACT_HASH = "sha256:55cb73827ab5129bd956ad2b70c485313fef6e148ebd9613235b7c74495f5d79"
"""The content hash the trainer emitted for the weights — a *pinned literal*, not a recomputation,
so any later hand edit is caught by the test that recomputes it. Hashed over a canonical sorted-key
view of ``(A_MAT, B_VEC)`` rather than the file bytes, so reformatting cannot break it."""


def _canonical(
    a_mat: dict[str, list[list[float]]] = A_MAT, b_vec: dict[str, list[float]] = B_VEC
) -> tuple:
    """A sorted-key, tuple-of-tuples view of the weights — the structure the hash is taken over."""
    return tuple(
        (name, tuple(tuple(row) for row in a_mat[name]), tuple(b_vec[name]))
        for name in sorted(a_mat)
    )


def compute_artifact_hash(
    a_mat: dict[str, list[list[float]]] = A_MAT, b_vec: dict[str, list[float]] = B_VEC
) -> str:
    """The canonical content hash of the weights — the recipe :data:`ARTIFACT_HASH` pins.

    A pure function of the data structure (via ``repr`` of :func:`_canonical`), shared by the
    offline trainer and the test that verifies the shipped artifact is exactly what the fit
    produced."""
    return "sha256:" + hashlib.sha256(repr(_canonical(a_mat, b_vec)).encode("utf-8")).hexdigest()


__all__ = [
    "MODEL_VERSION",
    "CORPUS_SHA256",
    "BUILD_PARAMS",
    "DIM",
    "ALPHA",
    "RIDGE",
    "A_MAT",
    "B_VEC",
    "ARTIFACT_HASH",
    "compute_artifact_hash",
]
