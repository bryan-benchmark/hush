"""Exp005A and Exp005B. Phrase lists and the matcher were fixed before ASR.

Fuzzy matching is for the transition phrases only. The commercial vocabulary
is exact tokens, because those items are short enough that an edit would
count ordinary words. Neither rule reads the commercial ledger.
"""

from __future__ import annotations

import re
import unicodedata

EXPERIMENT_SPEC_VERSION = "exp005-v1"
FEATURE_SCHEMA_VERSION = "exp005-language-v1"

MATCH_SIMILARITY = 0.85
MAX_SPAN_S = 8.0
MAX_GAP_S = 1.5

DEPARTURE_PHRASES = (
    "we'll be right back",
    "we'll be back",
    "stay with us",
    "coming up",
    "after the break",
    "after this",
    "timeout",
    "commercial break",
)
RETURN_PHRASES = (
    "welcome back",
    "we're back",
    "back here",
    "back to",
    "welcome back to",
    "let's get back to",
)
COMMERCIAL_VOCABULARY = (
    "visit",
    "call",
    "order",
    "shop",
    "buy",
    "save",
    "free",
    "offer",
    "limited time",
    "available now",
    "learn more",
    "sign up",
    "download",
    "ask your doctor",
    "talk to your doctor",
    "side effects",
    "terms apply",
    "restrictions apply",
    "participating locations",
)

# Applied to the phrase lists and to ASR text, so "we'll" and "we will" agree.
CONTRACTIONS = (
    ("we'll", "we will"),
    ("we're", "we are"),
    ("let's", "let us"),
    ("it's", "it is"),
    ("that's", "that is"),
    ("don't", "do not"),
    ("can't", "cannot"),
    ("won't", "will not"),
    ("you're", "you are"),
    ("they're", "they are"),
    ("i'm", "i am"),
    ("what's", "what is"),
    ("there's", "there is"),
    ("here's", "here is"),
)

_APOSTROPHES = str.maketrans(
    {
        "\u2019": "'",
        "\u2018": "'",
        "\u02bc": "'",
        "`": "'",
    }
)


def similarity(left: str, right: str) -> float:
    """1 minus the Levenshtein distance divided by the longer string."""
    if left == right:
        return 1.0
    if not left or not right:
        return 0.0
    rows = len(left) + 1
    cols = len(right) + 1
    previous = list(range(cols))
    for i in range(1, rows):
        current = [i]
        for j in range(1, cols):
            cost = 0 if left[i - 1] == right[j - 1] else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return 1.0 - previous[-1] / max(len(left), len(right))


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).translate(_APOSTROPHES).casefold()
    value = value.replace("&", " and ")
    cleaned = []
    for char in value:
        if char.isascii() and (char.isalnum() or char in {"'", " "}):
            cleaned.append(char)
        else:
            cleaned.append(" ")
    value = " ".join("".join(cleaned).split())
    for source, target in CONTRACTIONS:
        value = re.sub(rf"\b{re.escape(source)}\b", target, value)
    return " ".join(value.split())


def _tokens(text: str) -> tuple[str, ...]:
    normalized = normalize_text(text)
    if not normalized:
        return ()
    return tuple(normalized.split())


class _Phrase:
    def __init__(self, text: str, kind: str) -> None:
        self.text = text
        self.kind = kind
        self.tokens = _tokens(text)
        self.joined = " ".join(self.tokens)
        if not self.tokens:
            raise RuntimeError(f"phrase normalizes to nothing: {text}")


DEPARTURE = tuple(_Phrase(text, "departure") for text in DEPARTURE_PHRASES)
RETURN = tuple(_Phrase(text, "return") for text in RETURN_PHRASES)
TRANSITION = tuple(sorted([*DEPARTURE, *RETURN], key=lambda item: (-len(item.tokens), item.joined)))
VOCABULARY = tuple(sorted((_Phrase(text, "commercial") for text in COMMERCIAL_VOCABULARY), key=lambda item: -len(item.tokens)))

PARAMS = {
    "match_similarity": MATCH_SIMILARITY,
    "max_span_s": MAX_SPAN_S,
    "max_gap_s": MAX_GAP_S,
    "departure_phrases": list(DEPARTURE_PHRASES),
    "return_phrases": list(RETURN_PHRASES),
    "commercial_vocabulary": list(COMMERCIAL_VOCABULARY),
    "fuzzy_applies_to": "transition phrases only",
    "vocabulary_match": "exact contiguous tokens after the same normalization",
}


def word_tokens(words: list[dict]) -> list[dict]:
    """One record per normalized token, carrying the ASR word's times."""
    tokens = []
    for word in words:
        start = float(word["start"])
        end = float(word["end"])
        for text in _tokens(str(word["text"])):
            tokens.append({"text": text, "start": start, "end": end})
    return tokens


def _span_ok(span: list[dict]) -> bool:
    if span[-1]["end"] - span[0]["start"] > MAX_SPAN_S:
        return False
    return all(span[index + 1]["start"] - span[index]["end"] <= MAX_GAP_S for index in range(len(span) - 1))


def find_transitions(words: list[dict]) -> list[dict]:
    """Longest phrase wins. A hit consumes its tokens, so shorter phrases inside it do not.

    A window may be one token shorter or longer than the phrase. The joined
    strings must reach similarity 0.85. Words more than 1.5 s apart, or a
    span longer than 8 s, do not form a phrase.
    """
    tokens = word_tokens(words)
    hits = []
    index = 0
    while index < len(tokens):
        found = None
        for phrase in TRANSITION:
            lengths = [len(phrase.tokens)]
            if len(phrase.tokens) > 1:
                lengths.append(len(phrase.tokens) - 1)
            lengths.append(len(phrase.tokens) + 1)
            for length in lengths:
                if length < 1 or index + length > len(tokens):
                    continue
                span = tokens[index : index + length]
                if not _span_ok(span):
                    continue
                joined = " ".join(item["text"] for item in span)
                score = similarity(joined, phrase.joined)
                if score >= MATCH_SIMILARITY:
                    found = (phrase, span, score)
                    break
            if found is not None:
                break
        if found is None:
            index += 1
            continue
        phrase, span, score = found
        hits.append(
            {
                "kind": phrase.kind,
                "phrase": phrase.text,
                "matched_text": " ".join(item["text"] for item in span),
                "similarity": score,
                "start": span[0]["start"],
                "end": span[-1]["end"],
            }
        )
        index += len(span)
    return hits


def find_vocabulary(words: list[dict]) -> list[dict]:
    """Exact vocabulary hits. Longer items are tried first and consume their tokens."""
    tokens = word_tokens(words)
    hits = []
    index = 0
    while index < len(tokens):
        found = None
        for phrase in VOCABULARY:
            length = len(phrase.tokens)
            if index + length > len(tokens):
                continue
            span = tokens[index : index + length]
            if not _span_ok(span):
                continue
            if tuple(item["text"] for item in span) == phrase.tokens:
                found = (phrase, span)
                break
        if found is None:
            index += 1
            continue
        phrase, span = found
        hits.append(
            {
                "phrase": phrase.text,
                "start": span[0]["start"],
                "end": span[-1]["end"],
            }
        )
        index += len(span)
    return hits
