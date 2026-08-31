"""
detectors.py — fully custom PII span detection. No third-party
anonymization framework (e.g. Presidio), no trained model, no cloud
API calls — everything runs locally with plain Python.

Detection has three parts:

  1. STRUCTURED  — regex, for things with a fixed shape
                    (phone numbers, email, PAN, Aadhaar-style IDs,
                    pin codes, dates, ages).
  2. GENDER      — a small term list — a fixed vocabulary match,
                    nothing to generalize.
  3. NAME        — any capitalized word (or run of them) that isn't
                    common English. See the design note below — this
                    deliberately does NOT try to classify whether
                    something is "really" a person vs. an organization,
                    or whether it's "really" a name at all.

detect(text) returns a list of Span objects, each describing exactly
where a piece of PII sits in the text. This is the ONLY interface the
masking layer (mask_pii.py) depends on.

---------------------------------------------------------------------
DESIGN NOTE — why capitalization instead of a trained NER model:

An earlier version of this file called a small trained ML model
(ner_model.py) to classify PERSON vs ORG. It worked, but needed
hand-labeled training examples and still made real mistakes on
phrasing it hadn't seen.

The insight that replaced it: masking doesn't need to know WHAT
something is, only THAT it might be identifying. Over-masking a word
that turns out not to be a real name costs nothing — it still becomes
a reversible token and un-masks back to the exact original text
either way. Under-masking a real name is the actual risk. So instead
of a model trying to be precise, this uses one liberal, mechanical
rule: any capitalized word that isn't common English gets masked,
whether it's a person, a company, a pet's name, or anything else.
This needs zero training data, has no dependency on scikit-learn, and
in testing caught several multi-word organization names the trained
model got wrong (e.g. correctly keeping "Global Tech Systems" as one
entity instead of splitting it).

The trade-off, stated plainly: lower precision (it will occasionally
mask an ordinary capitalized word that isn't really identifying
information) in exchange for higher recall and zero training-data
dependency. For a masking system, that trade-off is the right one.
---------------------------------------------------------------------
"""

import re
from typing import List

from span_types import Span

TOKEN_RE = re.compile(r"[A-Za-z']+")


def _tokenize(text: str):
    return [(m.group(), m.start(), m.end()) for m in TOKEN_RE.finditer(text)]


# ---------------------------------------------------------------------
# Tier 1: structured detectors (regex) — deterministic, no false
# positives if the pattern is well-formed. Extend/adjust these for
# whatever ID formats your project actually needs to catch.
# ---------------------------------------------------------------------

_PATTERNS = {
    "EMAIL":    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    # Phone: liberal catch for 10+ digits (US/international), formatted 3-3-4,
    # and Indian format starting with 6-9. Goal is high recall, not precision.
    "PHONE":    re.compile(r"\b\d{10,}\b|\d{3}[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)|[6-9]\d{4}[-.\s]?\d{5}|[6-9]\d{9}|(?:\+\d{1,3}[-.\s]?)?\d{6,}"),
    "PAN":      re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    "AADHAAR":  re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),
    "PIN_CODE": re.compile(r"\b\d{6}\b"),
    "AGE":      re.compile(r"\b\d{1,3}(?=\s?(?:years old|yo\b|y/o|-year-old))"),
    "DATE":     re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b"),
}


def _structured_spans(text: str) -> List[Span]:
    spans = []
    for entity_type, pattern in _PATTERNS.items():
        for m in pattern.finditer(text):
            spans.append(Span(entity_type, m.start(), m.end(), m.group()))
    return spans


# ---------------------------------------------------------------------
# Gender: a term list, not an NER task.
# ---------------------------------------------------------------------

_GENDER_TERMS = {"male", "female", "man", "woman", "transgender", "non-binary"}


def _gender_spans(text: str) -> List[Span]:
    spans = []
    for word, start, end in _tokenize(text):
        if word.lower() in _GENDER_TERMS:
            spans.append(Span("GENDER", start, end, word))
    return spans


# ---------------------------------------------------------------------
# Name/org: liberal capitalized-word matching. No training data, no
# ML model — just "does this look like a proper noun".
# ---------------------------------------------------------------------

# Common capitalized-in-context words that should never trigger this
# on their own — sentence starters, pronouns, discourse words. This
# list matters more here than it did with the ML model, since it's
# now the ONLY thing standing between "Hi" and being masked.
_NEVER_ENTITY = {
    "i", "hi", "hello", "hey", "am", "is", "are", "was", "were",
    "the", "a", "an", "and", "or", "but",
    "this", "that", "these", "those",
    "he", "she", "they", "we", "you", "it",
    "my", "your", "his", "her", "their", "our",
    "please", "thank", "thanks", "yes", "no", "ok", "okay",
    "good", "morning", "afternoon", "evening", "calling", "regarding",
}

# words that can sit INSIDE a multi-word name without breaking it,
# e.g. "Bank of America", "Ministry of Health" — but only if a
# capitalized word follows immediately after
_CONNECTORS = {"of", "and", "&", "for", "the"}


def _is_entity_word(word: str) -> bool:
    return word[0].isupper() and len(word) > 1 and word.lower() not in _NEVER_ENTITY


def _name_spans(text: str) -> List[Span]:
    tokens = _tokenize(text)
    spans, i, n = [], 0, len(tokens)
    while i < n:
        word, start, end = tokens[i]
        if _is_entity_word(word):
            j, cur_end = i + 1, end
            # greedily extend through more capitalized words, allowing
            # a single connector word if capitalization resumes right after
            while j < n:
                w2, s2, e2 = tokens[j]
                if _is_entity_word(w2):
                    cur_end, j = e2, j + 1
                elif w2.lower() in _CONNECTORS and j + 1 < n and _is_entity_word(tokens[j + 1][0]):
                    cur_end, j = tokens[j + 1][2], j + 2
                else:
                    break
            spans.append(Span("NAME", start, cur_end, text[start:cur_end]))
            i = j
        else:
            i += 1
    return spans


def detect(text: str) -> List[Span]:
    spans = _structured_spans(text) + _gender_spans(text) + _name_spans(text)
    # resolve overlaps: keep the earliest/longest span, drop anything
    # fully contained inside one already kept (avoids double-masking)
    spans.sort(key=lambda s: (s.start, -(s.end - s.start)))
    kept, last_end = [], -1
    for s in spans:
        if s.start >= last_end:
            kept.append(s)
            last_end = s.end
    return kept
