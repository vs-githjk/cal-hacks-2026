"""Word list for the approval code (d3).

A code is two words from this list ("amber falcon"). The words are common, one to three syllables,
easy for speech-to-text, and phonetically distinct: no two share a prefix of 4 letters, no two end in
the same 4 letters, and every pair differs by at least 3 edits (checked in pay/tests/test_approval.py).
The list is data: changing it changes every future code, never an issued one (codes are stored hashed).
"""
from __future__ import annotations

WORDS: tuple[str, ...] = (
    "amber", "falcon", "river", "copper", "marble", "harbor", "velvet", "orchid",
    "summit", "lantern", "meadow", "walnut", "cobalt", "glacier", "saddle", "thunder",
    "willow", "anchor", "banjo", "cactus", "dragon", "engine", "forest", "garnet",
    "island", "jacket", "kettle", "ladder", "nickel", "olive", "pencil", "quartz",
    "turtle", "violin", "bridge", "desert", "eagle", "feather", "ginger", "hazel",
    "indigo", "jungle", "koala", "lemon", "napkin", "ocean", "piano", "rabbit",
    "spider", "tunnel", "castle", "donkey", "goblet", "igloo", "jigsaw", "kitten",
    "nutmeg", "oyster", "parrot", "ribbon", "squirrel", "apple", "canyon", "dolphin",
    "flute", "giraffe", "iceberg", "jaguar", "kayak", "lizard", "noodle", "pickle",
    "radish", "sailor", "tomato", "umbrella", "vulture", "yogurt", "zebra", "almond",
    "cherry", "fabric", "gravel", "harvest", "ivory", "jelly", "lagoon", "muffin",
    "orange", "sunset", "trumpet", "tractor", "compass", "blanket", "cabbage", "mirror",
    "puzzle", "pretzel", "beacon", "tulip", "valley", "waffle",
)

WORD_SET = frozenset(WORDS)
