"""Mathematical question families, generated with exact arithmetic and solvers."""

from __future__ import annotations

import math
import random
from fractions import Fraction
from itertools import permutations

import z3

from .. import prover
from .catalog import DIFFICULTIES, Request
from .content import REVERSALS


def number(value: int | Fraction) -> str:
    value = Fraction(value)
    return str(value.numerator) if value.denominator == 1 else str(value)


def number_words(value: int) -> str:
    small = (
        "zero one two three four five six seven eight nine ten eleven twelve thirteen "
        "fourteen fifteen sixteen seventeen eighteen nineteen"
    ).split()
    tens = "zero ten twenty thirty forty fifty sixty seventy eighty ninety".split()
    if value < 0:
        return "minus " + number_words(-value)
    if value < 20:
        return small[value]
    if value < 100:
        return tens[value // 10] + (" " + small[value % 10] if value % 10 else "")
    if value < 1000:
        return (
            small[value // 100]
            + " hundred"
            + (" " + number_words(value % 100) if value % 100 else "")
        )
    return str(value)


def checked_value(value: int | Fraction, expression: z3.ArithRef, steps: list[str]) -> dict:
    expected = z3.RealVal(str(Fraction(value)))
    valid, _ = prover.decide(expression == expected)
    if not valid:
        raise RuntimeError("Z3/exact arithmetic disagreement")
    return {
        "method": "z3-and-exact-arithmetic",
        "z3_version": prover.z3_version(),
        "independent_checker": "python-integer-and-fraction-arithmetic",
        "agree": True,
        "scope": "the stated mathematical rules, quantities and assumptions",
        "expression": str(expression),
        "exact_result": str(Fraction(value)),
        "steps": steps,
    }


def arithmetic(request: Request, rng: random.Random) -> dict:
    level = DIFFICULTIES[request.difficulty]
    topic = request.topic
    a, b, c = rng.randint(4, 18), rng.randint(2, 9), rng.randint(2, 7)
    unit = ""
    if topic == "arithmetic":
        if level == 1:
            stem = f"A workshop has {a} trays with {b} beads in each. How many beads are there?"
            value, expression = a * b, z3.IntVal(a) * b
            steps = [f"Multiply trays by beads per tray: {a} × {b} = {value}."]
        elif level == 2:
            stem = (
                f"A stall starts with {a} boxes holding {b} badges each and sells {c} badges. "
                "How many badges remain?"
            )
            value, expression = a * b - c, z3.IntVal(a) * b - c
            steps = [
                f"Initially there are {a} × {b} = {a * b} badges.",
                f"After selling {c}, {value} remain.",
            ]
        else:
            each = a * b - c
            stem = (
                f"A club orders {a} packs of {b * c} tokens, removes {c * c} damaged tokens, "
                f"then shares the rest equally among {c} teams. How many does each team get?"
            )
            value = each
            expression = (z3.RealVal(a) * (b * c) - c * c) / c
            steps = [
                f"The order contains {a * b * c} tokens.",
                f"Removing {c * c} leaves {a * b * c - c * c}.",
                f"Dividing by {c} gives {each} per team.",
            ]
    elif topic == "sequences":
        terms = [a]
        operations = []
        length = 4 + level
        for index in range(length):
            if level == 1 or (level == 3 and index % 2 == 0):
                terms.append(terms[-1] + b)
                operations.append(f"add {b}")
            else:
                terms.append(terms[-1] * c)
                operations.append(f"multiply by {c}")
        rule = (
            f"add {b} each time"
            if level == 1
            else f"multiply by {c} each time"
            if level == 2
            else f"alternate adding {b} and multiplying by {c}, starting with addition"
        )
        stem = (
            f"A display follows this rule: {rule}. It shows "
            f"{', '.join(map(str, terms[:-1]))}. What value comes next?"
        )
        value = terms[-1]
        expression = z3.IntVal(a)
        for index in range(length):
            expression = (
                expression + b if level == 1 or (level == 3 and index % 2 == 0) else expression * c
            )
        steps = [
            f"The next operation is to {operations[-1]}.",
            f"Apply it to {terms[-2]} to get {value}.",
        ]
    elif topic == "motion":
        unit = "m/s"
        if level == 1:
            stem = (
                f"A cart travels {a * b} metres in {b} seconds at constant speed. "
                "Use speed = distance / time. What is its speed in m/s?"
            )
            value, expression = a, z3.RealVal(a * b) / b
            steps = [f"Divide {a * b} metres by {b} seconds to get {a} m/s."]
        elif level == 2:
            stem = (
                f"A robot travels {a * b} m in {b} s, then {a * c} m in {c} s. "
                "Average speed = total distance / total time. What is its average speed in m/s?"
            )
            value, expression = a, (z3.RealVal(a * b) + a * c) / (b + c)
            steps = [
                f"Total distance is {a * (b + c)} m and total time is {b + c} s.",
                f"Their ratio is {a} m/s.",
            ]
        else:
            stem = (
                f"A rover travels {a * b * 60} m in {b} minutes, then {a * c * 60} m in "
                f"{c} minutes. Average speed = total distance / total time. "
                "What is the average in m/s?"
            )
            value, expression = a, (z3.RealVal(a * b * 60) + a * c * 60) / ((b + c) * 60)
            steps = [
                f"Total distance is {a * (b + c) * 60} m.",
                f"Convert {b + c} minutes to {(b + c) * 60} seconds.",
                f"Divide to obtain {a} m/s.",
            ]
    elif topic == "circuits":
        unit = "A"
        if level == 1:
            stem = (
                f"An ideal resistor has resistance {b} ohms and voltage {a * b} volts. "
                "Use current = voltage / resistance. What is the current in amperes?"
            )
            value, expression = a, z3.RealVal(a * b) / b
            steps = [f"Current is {a * b} / {b} = {a} A."]
        elif level == 2:
            stem = (
                f"Two ideal resistors of {b} and {c} ohms are in series "
                f"across {a * (b + c)} volts. "
                "Series resistances add; current = voltage / total resistance. "
                "What is the current in amperes?"
            )
            value, expression = a, z3.RealVal(a * (b + c)) / (b + c)
            steps = [
                f"Total resistance is {b + c} ohms.",
                f"Current is {a * (b + c)} / {b + c} = {a} A.",
            ]
        else:
            voltage = a * b * c
            stem = (
                f"Ideal resistors of {b} and {c} ohms are in parallel across {voltage} volts. "
                "Each branch current equals voltage / branch resistance; branch currents add. "
                "What is the total current in amperes?"
            )
            value, expression = a * (b + c), z3.RealVal(voltage) / b + z3.RealVal(voltage) / c
            steps = [
                f"The branch currents are {a * c} A and {a * b} A.",
                f"Add them to obtain {value} A.",
            ]
    elif topic == "density":
        unit = "g/cm³"
        if level == 1:
            stem = (
                f"A sample has mass {a * b} g and volume {b} cm³. "
                "Density = mass / volume. What is its density in g/cm³?"
            )
            value, expression = a, z3.RealVal(a * b) / b
            steps = [f"Density is {a * b} / {b} = {a} g/cm³."]
        elif level == 2:
            stem = (
                f"Two blocks of the same material have total mass {a * (b + c)} g and volumes "
                f"{b} and {c} cm³. Density = total mass / total volume. "
                "What is their density in g/cm³?"
            )
            value, expression = a, z3.RealVal(a * (b + c)) / (b + c)
            steps = [
                f"The volumes add to {b + c} cm³.",
                f"Divide the mass by that to get {a} g/cm³.",
            ]
        else:
            stem = (
                f"A sample has mass {a * b} kg and volume {b * 1000} cm³. "
                "There are 1000 grams in a kilogram; density = mass / volume. "
                "What is its density in g/cm³?"
            )
            value, expression = a, z3.RealVal(a * b) * 1000 / (b * 1000)
            steps = [
                f"Convert {a * b} kg to {a * b * 1000} g.",
                f"Divide by {b * 1000} cm³ to obtain {a} g/cm³.",
            ]
    else:
        raise ValueError("Unknown arithmetic family")
    proof = checked_value(value, expression, steps)
    return {
        "stem": stem,
        "value": value,
        "unit": unit,
        "proof": proof,
        "lesson": "calculation",
        "explanation": " ".join(steps),
    }


def ordering(request: Request, rng: random.Random) -> dict:
    count = DIFFICULTIES[request.difficulty] + 3
    names = rng.sample(("Asha", "Ben", "Cleo", "Dev", "Eli", "Faye", "Gus", "Hana"), count)
    target = rng.randrange(count)
    rules = list(zip(names[:-1], names[1:], strict=True))
    rng.shuffle(rules)
    stem = (
        f"{', '.join(rng.sample(names, len(names)))} stand in a row. "
        + " ".join(f"{a} stands to the left of {b}." for a, b in rules)
        + f" Counting from the left as position 1, what position does {names[target]} occupy?"
    )
    orders = [
        row for row in permutations(names) if all(row.index(a) < row.index(b) for a, b in rules)
    ]
    if len(orders) != 1 or orders[0][target] != names[target]:
        raise RuntimeError("Ordering enumeration failed")
    positions = {name: z3.Int(name) for name in names}
    premises = z3.And(
        *[z3.And(p >= 1, p <= count) for p in positions.values()],
        z3.Distinct(*positions.values()),
        *[positions[a] < positions[b] for a, b in rules],
    )
    sat, _ = prover.satisfiable(premises)
    valid, _ = prover.decide(z3.Implies(premises, positions[names[target]] == target + 1))
    if not sat or not valid:
        raise RuntimeError("Z3/permutation disagreement")
    steps = [
        f"The only order satisfying every clue is {', '.join(names)}.",
        f"{names[target]} is in position {target + 1}.",
    ]
    return {
        "stem": stem,
        "value": target + 1,
        "unit": "",
        "lesson": "ordering",
        "explanation": " ".join(steps),
        "proof": {
            "method": "z3-and-permutation-enumeration",
            "agree": True,
            "z3_version": prover.z3_version(),
            "possible_orders": [list(orders[0])],
            "scope": "the stated ordering constraints",
            "steps": steps,
        },
    }


def mystery(request: Request, rng: random.Random) -> dict:
    level = DIFFICULTIES[request.difficulty]
    width = (20, 70, 200)[level - 1]
    for _ in range(200):
        lower = rng.randint(1, 60)
        upper = lower + width
        value = rng.randint(lower, upper)
        modulus = rng.choice((3, 4, 7, 8, 9))
        remainder = value % modulus
        digit_sum = sum(map(int, str(value)))
        second = rng.choice((5, 7, 11, 13))

        def satisfies(
            n, modulus=modulus, remainder=remainder, digit_sum=digit_sum, value=value, second=second
        ):
            return (
                n % modulus == remainder
                and sum(map(int, str(n))) == digit_sum
                and (level < 2 or n % 2 == value % 2)
                and (level < 3 or n % second == value % second)
            )

        survivors = [n for n in range(lower, upper + 1) if satisfies(n)]
        if survivors == [value]:
            break
    else:
        raise RuntimeError("Could not find a unique number mystery")
    clauses = [
        f"I am a whole number from {lower} to {upper}, inclusive.",
        f"Dividing me by {modulus} leaves remainder {remainder}.",
        f"My decimal digits add to {digit_sum}.",
    ]
    x = z3.Int("hidden_number")
    constraints = [
        x >= lower,
        x <= upper,
        x % modulus == remainder,
        x / 100 + (x / 10) % 10 + x % 10 == digit_sum,
    ]
    if level >= 2:
        clauses.append(f"I am {'even' if value % 2 == 0 else 'odd'}.")
        constraints.append(x % 2 == value % 2)
    if level >= 3:
        clauses.append(f"Dividing me by {second} leaves remainder {value % second}.")
        constraints.append(x % second == value % second)
    premises = z3.And(*constraints)
    sat, _ = prover.satisfiable(premises)
    valid, _ = prover.decide(z3.Implies(premises, x == value))
    if not sat or not valid:
        raise RuntimeError("Z3/number enumeration disagreement")
    steps = [
        f"Checking every integer from {lower} to {upper} leaves only {value}.",
        f"Its digit sum is {digit_sum} and its remainder modulo {modulus} is {remainder}.",
    ]
    return {
        "stem": " ".join([*clauses, "What number am I?"]),
        "value": value,
        "unit": "",
        "lesson": "number-riddles",
        "explanation": " ".join(steps),
        "proof": {
            "method": "z3-and-finite-integer-enumeration",
            "agree": True,
            "z3_version": prover.z3_version(),
            "range": [lower, upper],
            "survivors": survivors,
            "scope": "unique integer satisfying all stated clues",
            "steps": steps,
        },
    }


def word_riddle(request: Request, rng: random.Random) -> dict:
    source, answer = rng.choice(REVERSALS[request.difficulty])
    if (
        source[::-1] != answer
        or "".join(source[i] for i in range(len(source) - 1, -1, -1)) != answer
    ):
        raise RuntimeError("Reversal dictionary is inconsistent")
    return {
        "stem": f"Read {source} from right to left without adding or removing letters. "
        f"I am the resulting {len(answer)}-letter English word. What am I?",
        "answer": answer.lower(),
        "lesson": "word-riddles",
        "distractors": [b.lower() for pairs in REVERSALS.values() for _, b in pairs if b != answer],
        "aliases": [answer.lower(), f"the word {answer.lower()}", f"answer: {answer.lower()}"],
        "explanation": (
            f"Reversing the letter order of {source} gives {answer}. "
            "Each original letter is used exactly once."
        ),
        "proof": {
            "method": "exact-letter-transformation",
            "source": source,
            "result": answer,
            "scope": "letter reversal; the vocabulary is curated English",
            "steps": [f"Reverse {' '.join(source)} to obtain {' '.join(answer)}."],
        },
    }


def wonder(request: Request, rng: random.Random) -> dict:
    level = DIFFICULTIES[request.difficulty]
    if request.topic == "growth":
        stages = rng.randint(3 + (level - 1) * 5, 7 + (level - 1) * 5)
        start = rng.randint(1, 6)
        value = start
        for _ in range(stages):
            value *= 2
        steps = [
            f"Starting with {start}, double the total {stages} times.",
            f"The result is {start} × 2^{stages} = {value:,}.",
        ]
        proof = checked_value(value, z3.IntVal(start) * 2**stages, steps)
        hook = (
            f"Imagine starting with {start} counters and doubling the total {stages} times. "
            "Before calculating, how large do you think the pile becomes?"
        )
        insight = (
            f"It reaches {value:,} counters. Each step doubles everything already there, "
            "so the final steps contribute far more than the early ones. "
            "This is an ideal mathematical model with no limit on space or materials."
        )
        share = (
            f"Ask someone to estimate {start} doubled {stages} times "
            "before showing the calculation."
        )
    elif request.topic == "probability":
        count = rng.randint(*((10, 20), (21, 30), (31, 45))[level - 1])
        no_match = Fraction(1)
        for i in range(count):
            no_match *= Fraction(365 - i, 365)
        independent = Fraction(math.perm(365, count), 365**count)
        if no_match != independent:
            raise RuntimeError("Birthday probability cross-check failed")
        chance = 1 - no_match
        hook = (
            f"In a group of {count} people, how surprising would a shared birthday be? "
            "Assume independent birthdays equally likely on 365 days, ignoring leap days."
        )
        insight = (
            f"The chance of at least one shared birthday is about {float(chance) * 100:.2f}%. "
            f"There are {math.comb(count, 2)} pairs, not just comparisons with your own birthday. "
            "Real birthday distributions are not perfectly uniform."
        )
        steps = [
            "Multiply 365/365 × 364/365 × ... for the probability of no shared birthday.",
            "Subtract that probability from one to get the probability of at least one match.",
        ]
        proof = {
            "method": "exact-probability-two-formulas",
            "exact_probability": str(chance),
            "people": count,
            "days": 365,
            "steps": steps,
            "scope": "the stated independent uniform-birthday model",
        }
        share = (
            f"Would you have expected a shared birthday among {count} people? "
            "Explain why pairs matter."
        )
    else:
        boxes, guaranteed = rng.randint(3, 6 + level), level + 1
        count = boxes * (guaranteed - 1) + 1
        if math.ceil(Fraction(count, boxes)) != guaranteed or boxes * (guaranteed - 1) >= count:
            raise RuntimeError("Pigeonhole bound failed")
        hook = (
            f"Place {count} stones into {boxes} bowls in any arrangement, allowing empty bowls. "
            f"Can you keep every bowl below {guaranteed} stones?"
        )
        insight = (
            f"At least one bowl must contain {guaranteed} or more stones. "
            f"If every bowl held at most {guaranteed - 1}, they would hold only "
            f"{boxes * (guaranteed - 1)} altogether. "
            "One more stone makes the guarantee unavoidable."
        )
        steps = [
            f"Capacity below the threshold is {boxes} × {guaranteed - 1} = {count - 1}.",
            f"There are {count} stones, so at least one bowl crosses the threshold.",
        ]
        proof = checked_value(guaranteed, z3.IntVal(count + boxes - 1) / boxes, steps)
        share = (
            "Where else could counting places and objects force a match, "
            "even without knowing the arrangement?"
        )
    return {"stem": hook, "insight": insight, "share": share, "proof": proof}
