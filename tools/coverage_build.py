"""Rebuild frozen v1/v2 packs from pinned OEWN senses and authored additions."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from spie.questions.brainbloom.coverage_sources import (
    OEWN_SHA256,
    PACKS_SHA256,
    PACKS_V2_SHA256,
    load_oewn,
)

# Reviewed selections: lemma | exact upstream synset | adapted crossword clue.
# These are editorial topic memberships, not OEWN graph edges or solver facts.
SELECTIONS = {
    "machine learning": (
        "ml;statistical learning",
        "Statistical and computing vocabulary",
        """
algorithm|05855965|A precise sequence of rules for solving a problem
data|08479331|A collection of recorded facts or observations
classification|01014654|The act of assigning things to categories
regression|06036794|Statistical modelling of a response in relation to explanatory variables
model|05898856|A simplified representation of a system or process
feature|05858316|An attribute used to describe an observation
clustering|07976557|The grouping of similar observations
neural network|06738216|A computing model with connected units inspired by neurons
prediction|05783078|An estimate of an unknown or future outcome
sample|06036061|A selection of observations from a population
parameter|05867861|A numerical quantity characterising a statistical population
accuracy|04810156|Closeness of a result to the correct or true value
""",
    ),
    "cybersecurity": (
        "cyber security;computer security",
        "Computer protection vocabulary",
        """
firewall|03352988|A security system that filters traffic between computers or networks
encryption|00617127|The conversion of readable information into coded form
malware|06600315|Software designed to harm, disrupt or compromise a computer system
password|06686933|A secret word or phrase used to help control access
authentication|00155053|The process of checking a claimed identity or origin
ransomware|90009981|Malicious software that blocks access and demands payment
cipher|06366714|A method for transforming a message into a secret form
backup|02774845|A separate copy of stored data kept for recovery
cryptography|00615776|The practice of protecting information through codes and ciphers
network|08451269|An interconnected system of devices or other components
decryption|00618299|The conversion of coded information back into readable form
vulnerability|05050025|A weakness that leaves a system susceptible to attack
""",
    ),
    "renewable energy": (
        "renewables;clean energy vocabulary",
        "Renewable generation and storage vocabulary",
        """
solar energy|11530115|Energy from sunlight that can be converted into heat or electricity
wind power|11547345|Power obtained from moving air
turbine|04505818|A machine whose bladed rotor is turned by a moving fluid
generator|03438787|A machine that converts mechanical energy into electrical energy
battery|02813606|A device of one or more cells that supplies electrical energy
biomass|14709079|Plant material or animal waste used as fuel
inverter|03588128|A device that converts direct current into alternating current
electricity|11470903|Energy supplied by the movement of electric charge
solar cell|04265096|A device that converts sunlight directly into electrical energy
windmill|04594862|A mill driven by the wind
energy|11472635|A physical quantity measured in joules and associated with the ability to do work
rotor|04119056|The rotating part of a motor or generator
""",
    ),
    "robotics": (
        "robot engineering",
        "Robot components and control vocabulary",
        """
robot|02764397|A programmable machine that carries out actions automatically
sensor|03185635|A device that detects and responds to a physical signal
actuator|02681238|A mechanism that produces movement or other action in a machine
servo|04183356|A powered control mechanism that uses feedback to follow a command
feedback|13500583|The return of part of a system's output to regulate its input
automation|00103277|The use of technology to control equipment with reduced human intervention
controller|03101611|A mechanism that regulates the operation of a machine
motor|03795479|A machine that converts energy into mechanical motion
kinematics|06123384|The study of motion without considering its forces or masses
joint|03606190|A connection where separate mechanical parts are joined
arm|02740838|A projecting machine part resembling a human upper limb
robotics|06143105|The study and practical use of programmable machines
""",
    ),
    "plate tectonics": (
        "tectonic plates",
        "Earth structure and plate movement vocabulary",
        """
crust|09282916|The outermost solid layer of Earth
mantle|09369347|The layer of Earth between its crust and core
plate|09418350|A rigid piece of Earth's lithosphere that moves relative to other pieces
subduction|13583883|The movement of one tectonic plate down beneath another
fault|09301443|A fracture in rock along which displacement has occurred
earthquake|07443554|Shaking of Earth's surface caused by a sudden release of energy
volcano|09493680|A vent through which molten rock and gases reach a planetary surface
rift|09432904|A narrow fissure or opening in rock
magma|14955933|Molten rock beneath Earth's surface
lava|14955127|Molten rock that has reached a planetary surface
tectonics|06127977|The study of deformation and large structures of Earth's crust
continent|09277520|One of Earth's large landmasses
""",
    ),
    "genetics": (
        "heredity vocabulary;genomics",
        "Heredity and cell division vocabulary",
        """
gene|05444328|A hereditary sequence that contributes to a functional RNA or protein product
chromosome|05449707|A structure of DNA and associated proteins that carries genes
genome|08474554|An organism's complete set of genetic material
allele|05445361|An alternative form of a gene at a particular locus
mutation|07439611|A change in a genetic sequence
heredity|13514602|The transmission of biological characteristics between generations
genotype|04941220|The combination of alleles at specified genetic loci
phenotype|04941029|Observable characteristics arising from genes and the environment
meiosis|13533928|Cell division that reduces the chromosome number by half
mitosis|13537800|Nuclear division that normally preserves the chromosome number
nucleotide|14988729|A basic molecular building block of DNA or RNA
genetics|06085077|The branch of biology concerned with heredity and variation
""",
    ),
    "cricket": (
        "cricket sport;cricket vocabulary",
        "Cricket sport vocabulary, excluding the insect meaning",
        """
bat|03136727|The club used to strike the ball in cricket
ball|02781674|The round object delivered by the bowler in cricket
wicket|04590155|A set of three stumps topped by two bails in cricket
bowler|09889502|The cricket player who delivers the ball to the batter
innings|00458252|A batting turn of a cricket player or team
over|15283505|A set of six valid deliveries by one cricket bowler
stump|04353081|One of the three upright posts forming a cricket wicket
cricketer|09996856|An athlete who plays the bat-and-ball sport with eleven players per side
googly|00478108|A leg-spinner's delivery that turns in the opposite direction to the usual leg break
fielder|10106152|A cricket player on the side trying to stop runs and take wickets
duck|13617087|A batter's score of zero in cricket
follow-on|00458062|A second consecutive innings required of a trailing cricket team under the rules
""",
    ),
    "neuroscience": (
        "brain science;neural biology",
        "Nervous system anatomy vocabulary",
        """
neuron|05473219|A cell specialised for transmitting nerve signals
axon|05476501|A nerve cell extension that usually carries signals away from its body
dendrite|05477513|A branching nerve cell extension that commonly receives signals
synapse|05481580|A junction through which a neuron communicates with another cell
cortex|05494162|The outer layer of grey matter of the cerebrum
cerebellum|05493206|A brain region important for coordination and motor learning
hippocampus|05503912|A brain structure with a central role in forming memories
nerve|05481998|A bundle of fibres carrying signals through the body
brain|05488747|The part of the central nervous system enclosed by the skull
myelin|14982032|A fatty insulating material surrounding many nerve fibres
spinal cord|05511356|The long central nervous structure linking the brain with many body nerves
cerebrum|05499645|The large upper brain region divided into two hemispheres
""",
    ),
}


# Original project-authored additions, preserved separately from upstream senses.
# These definitions are not claims about OEWN contents or graph relationships.
AUTHORED_V2 = """
optimizer|A procedure that adjusts model parameters to reduce error
embedding|A representation that places related items near one another
latent|Present but not directly observed in a model
epoch|One complete pass through a training collection
batch|A group of examples processed together
gradient|A direction of steepest increase in a function
inference|The act of producing a model result from input
tokenizer|A component that divides text into model units
calibration|Adjustment of outputs so confidence matches observed frequency
regularization|A method that discourages overly complex model parameters
"""


def build(path: Path, version: str = "v2") -> bytes:
    if version not in ("v1", "v2"):
        raise ValueError("version must be v1 or v2")
    synsets, _, _ = load_oewn(path)
    packs = []
    for topic, (aliases, definition, rows) in SELECTIONS.items():
        pid = "coverage-v1:" + topic.replace(" ", "-")
        entries = []
        for row in rows.strip().splitlines():
            lemma, offset, clue = row.split("|")
            sid = f"oewn2024:oewn-{offset}-n"
            node = synsets[sid]
            assert lemma.replace(" ", "_") in node["words"], (lemma, sid)
            word = lemma.replace(" ", "").replace("-", "").upper()
            assert 3 <= len(word) <= 15
            entries.append(
                {
                    "word": word,
                    "lemma": lemma,
                    "definition": clue,
                    "source_sense": sid,
                    "source_definition": node["definition"],
                }
            )
        packs.append(
            {
                "id": pid,
                "topic": topic,
                "aliases": aliases.split(";"),
                "definition": definition,
                "entries": entries,
            }
        )
    result = {
        "schema": 1,
        "version": "coverage-packs-v1",
        "source_sha256": OEWN_SHA256,
        "review": {
            "date": "2026-09-30",
            "reviewer": "Codex agent editorial review",
            "human_review": False,
            "scope": "Sense selection, topic relevance, clue wording, answer leakage, length",
            "limits": "Not an independent subject expert review or player study",
        },
        "transformations": "Selected lemmas and synsets; adapted, shortened definitions; "
        "editorial topic memberships; spaces and hyphens removed in answers",
        "packs": packs,
    }
    if version == "v2":
        result.update(
            schema=2,
            version="coverage-packs-v2",
            review={
                "date": "2026-09-30",
                "reviewer": "Repository editorial review",
                "human_review": False,
                "scope": "Sense selection topic relevance clue wording answer leakage length",
                "limits": "Authored static extension; not independent subject expert "
                "review or player study",
            },
            transformations="Selected authored lexical meanings; source-qualified pack IDs; "
            "editorial topic memberships; spaces and hyphens removed in answers",
        )
        for pack in packs:
            pack["id"] = pack["id"].replace("coverage-v1:", "coverage-v2:", 1)
        for row in AUTHORED_V2.strip().splitlines():
            lemma, definition = row.split("|", 1)
            packs[0]["entries"].append(
                {
                    "word": lemma.upper(),
                    "lemma": lemma,
                    "definition": definition,
                    "source_sense": "authored-v2:" + lemma,
                    "source_definition": definition,
                }
            )
    # v1 was frozen with LF; v2 was frozen with CRLF. Reproduce the exact bytes
    # on every operating system without editing either original snapshot.
    newline = "\r\n" if version == "v2" else "\n"
    data = (
        (json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        .replace("\n", newline)
        .encode("utf-8")
    )
    expected = PACKS_V2_SHA256 if version == "v2" else PACKS_SHA256
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"Rebuilt {version} does not match its pinned snapshot SHA256")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument(
        "--version",
        choices=("v1", "v2"),
        default="v2",
        help="Frozen snapshot to rebuild (default: v2)",
    )
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error(f"Refusing to overwrite: {args.out}")
    data = build(args.source, args.version)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("xb") as stream:
        stream.write(data)
    print(hashlib.sha256(data).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
