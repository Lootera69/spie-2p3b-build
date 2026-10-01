"""Controlled lexical normalization keeps provenance and ambiguity visible."""

from spie.questions.brainbloom.lexicon import Dictionary


def test_phrase_alias_is_labeled_and_keeps_authored_source():
    result = Dictionary().lookup("black holes")
    assert result["status"] == "ready"
    choice = result["choices"][0]
    assert choice["normalization"] == "phrase-alias"
    assert choice["normalized_term"] == "black hole"
    assert choice["provenance"] == "authored-alias"
    assert result["context"]["source"]["name"] == "BrainBloom authored vocabulary v1"


def test_safe_plural_and_spelling_variant_are_explicit():
    dictionary = Dictionary()
    plural = dictionary._matches("oceans")
    assert plural and plural[0]["normalization"] == "phrase-alias"
    # A spelling rule is not accepted merely because a target spelling exists
    # in the rule table; it must resolve to a loaded source entry.
    assert dictionary._matches("colour") == []


def test_unknown_plural_is_not_silently_collapsed():
    assert Dictionary().lookup("widgets")["status"] == "unknown"
