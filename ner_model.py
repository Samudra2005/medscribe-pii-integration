"""
ner_model.py — a small, genuinely-trained NER model for PERSON and ORG
entities. No pretrained weights, no spaCy/Presidio/HuggingFace model,
no network calls. Just hand-labeled example sentences + scikit-learn's
plain LogisticRegression, treating NER as one classification decision
per token (predict a BIO tag for every word), which is a standard
approach and doesn't require any specialized sequence-labeling library.

This is a genuine improvement over a name dictionary: it generalizes
to names/orgs it has never seen, using contextual and shape features
(capitalization, position, neighboring words, known org-suffix words
like "Hospital" or "Technologies") rather than exact string matching.

Honest limitation: it's trained on ~40 hand-written example sentences,
which is enough to prove the pipeline works and generalizes, but far
short of production accuracy. To scale this up without touching any
licensed dataset: generate thousands of synthetic labeled sentences
from templates + name/org lists (fully yours, zero licensing risk), or
label real de-identified examples from your own domain — the second
option will likely beat any generic public dataset anyway, since it
matches exactly the kind of speech your app actually sees.
"""

import re
from typing import List, Tuple

from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression

from span_types import Span

TOKEN_RE = re.compile(r"[A-Za-z']+")


def tokenize(text: str) -> List[Tuple[str, int, int]]:
    """Return (word, start, end) for every word-like token in text."""
    return [(m.group(), m.start(), m.end()) for m in TOKEN_RE.finditer(text)]


# ---------------------------------------------------------------------
# Training data: hand-labeled example sentences.
# Each entry gives the sentence plus (substring, label) pairs — the
# character offsets are found automatically so there's no manual
# counting to get wrong.
# ---------------------------------------------------------------------

def _example(text: str, entities: List[Tuple[str, str]]):
    spans = []
    for substring, label in entities:
        idx = text.index(substring)
        spans.append((idx, idx + len(substring), label))
    return text, spans


TRAIN_EXAMPLES = [
    _example("Hi, I am Rahul Sharma calling from Apollo Hospital.",
             [("Rahul Sharma", "PERSON"), ("Apollo Hospital", "ORG")]),
    _example("My name is Priya Nair and I work at Infosys Technologies.",
             [("Priya Nair", "PERSON"), ("Infosys Technologies", "ORG")]),
    _example("This is Dr. Aditya Verma from Fortis Clinic.",
             [("Aditya Verma", "PERSON"), ("Fortis Clinic", "ORG")]),
    _example("I'm Wei Zhang, I recently joined Tata Consultancy Services.",
             [("Wei Zhang", "PERSON"), ("Tata Consultancy Services", "ORG")]),
    _example("You can reach Fatima Khan at the front desk.",
             [("Fatima Khan", "PERSON")]),
    _example("Sara Thompson has an appointment with Dr. Lee tomorrow.",
             [("Sara Thompson", "PERSON"), ("Lee", "PERSON")]),
    _example("The invoice was sent by Reliance Insurance Group.",
             [("Reliance Insurance Group", "ORG")]),
    _example("Please contact John Miller regarding the claim.",
             [("John Miller", "PERSON")]),
    _example("I studied at Delhi University before joining HDFC Bank.",
             [("Delhi University", "ORG"), ("HDFC Bank", "ORG")]),
    _example("Mrs. Gupta mentioned that Cipla Pharmaceuticals sponsors the ward.",
             [("Gupta", "PERSON"), ("Cipla Pharmaceuticals", "ORG")]),
    _example("Aravind Nair transferred from Manipal Hospitals last week.",
             [("Aravind Nair", "PERSON"), ("Manipal Hospitals", "ORG")]),
    _example("This is regarding a claim filed by Meera Iyer.",
             [("Meera Iyer", "PERSON")]),
    _example("Our records show Kevin O'Brien joined via Star Health Insurance.",
             [("Kevin O'Brien", "PERSON"), ("Star Health Insurance", "ORG")]),
    _example("I would like to schedule Ananya Reddy for a follow-up.",
             [("Ananya Reddy", "PERSON")]),
    _example("The referral came from Max Healthcare Institute.",
             [("Max Healthcare Institute", "ORG")]),
    _example("Please update the file for patient Arjun Malhotra.",
             [("Arjun Malhotra", "PERSON")]),
    _example("Dr. Sanjay Mehta will see you after the scan.",
             [("Sanjay Mehta", "PERSON")]),
    _example("The report was reviewed by Sunrise Diagnostics Pvt Ltd.",
             [("Sunrise Diagnostics Pvt Ltd", "ORG")]),
    _example("Neha Kapoor called about her prescription refill.",
             [("Neha Kapoor", "PERSON")]),
    _example("This policy is underwritten by ICICI Lombard.",
             [("ICICI Lombard", "ORG")]),
    _example("Good morning, my name is Thomas Reid.",
             [("Thomas Reid", "PERSON")]),
    _example("The lab results came from Metropolis Healthcare.",
             [("Metropolis Healthcare", "ORG")]),
    _example("Vikram Chatterjee is the attending physician on this case.",
             [("Vikram Chatterjee", "PERSON")]),
    _example("She previously worked at Wipro Limited for six years.",
             [("Wipro Limited", "ORG")]),
    _example("Please note that Isha Bhatt requested a second opinion.",
             [("Isha Bhatt", "PERSON")]),
    _example("Contact our billing partner, Sunshine Billing Solutions.",
             [("Sunshine Billing Solutions", "ORG")]),
    _example("Michael Chen submitted the form yesterday afternoon.",
             [("Michael Chen", "PERSON")]),
    _example("The device was manufactured by MedTech Innovations Inc.",
             [("MedTech Innovations Inc", "ORG")]),
    _example("Dr. Kavya Menon transferred the patient this morning.",
             [("Kavya Menon", "PERSON")]),
    _example("I want to check my coverage under Bajaj Allianz.",
             [("Bajaj Allianz", "ORG")]),
    _example("Rohan Desai has been on the waiting list since March.",
             [("Rohan Desai", "PERSON")]),
    _example("This request comes from the compliance team at Google.",
             [("Google", "ORG")]),
    _example("Good afternoon, this is Emily Clarke speaking.",
             [("Emily Clarke", "PERSON")]),
    _example("The scan was booked through Apollo Diagnostics.",
             [("Apollo Diagnostics", "ORG")]),
    _example("Can you confirm the appointment time for tomorrow?", []),
    _example("The results should be ready within two business days.", []),
    _example("Please hold while I transfer your call.", []),
    _example("Thank you for waiting, how can I help today?", []),
]


# ---------------------------------------------------------------------
# Feature extraction: what the model actually looks at per token
# ---------------------------------------------------------------------

ORG_SUFFIXES = {
    "inc", "ltd", "llc", "corp", "corporation", "pvt", "hospital", "hospitals",
    "clinic", "university", "college", "bank", "institute", "group",
    "technologies", "technology", "systems", "solutions", "insurance",
    "labs", "laboratories", "pharma", "pharmaceuticals", "healthcare",
    "diagnostics", "limited", "services", "consultancy",
}
TITLES = {"mr", "mrs", "ms", "dr"}

# Common function words the classifier can otherwise mistake for the
# start of a name — e.g. "I" is always capitalized regardless of
# position, which looks like a name-boundary signal with this little
# training data. These can never be an entity, full stop, regardless
# of what the classifier predicts for them.
_NEVER_ENTITY = {
    "i", "hi", "hello", "hey", "am", "is", "are", "was", "were",
    "the", "a", "an", "and", "or", "but", "this", "that",
    "he", "she", "they", "we", "you", "it",
    "my", "your", "his", "her", "their", "our",
}


def _features(tokens, i, prev_tag):
    word = tokens[i][0]
    f = {
        "word.lower": word.lower(),
        "word.istitle": word.istitle(),
        "word.isupper": word.isupper(),
        "word.suffix3": word[-3:].lower(),
        "is_first": i == 0,
        "is_org_suffix_word": word.lower() in ORG_SUFFIXES,
        "prev_tag": prev_tag,  # lets the model learn tag-to-tag patterns,
                               # e.g. "after B-ORG, a capitalized word is
                               # likely I-ORG" — this is what actually
                               # fixes multi-word entity boundaries
    }
    prev_word = tokens[i - 1][0] if i > 0 else "<START>"
    next_word = tokens[i + 1][0] if i < len(tokens) - 1 else "<END>"
    f["prev.lower"] = prev_word.lower()
    f["prev.is_title_honorific"] = prev_word.lower().rstrip(".") in TITLES
    f["next.lower"] = next_word.lower()
    f["next.istitle"] = next_word[:1].isupper()
    return f


def _to_bio(text, entity_spans):
    tokens = tokenize(text)
    tags = []
    for word, start, end in tokens:
        tag = "O"
        for e_start, e_end, label in entity_spans:
            if start >= e_start and end <= e_end:
                tag = ("B-" if start == e_start else "I-") + label
                break
        tags.append(tag)
    return tokens, tags


def _build_training_set():
    X_dicts, y = [], []
    for text, entities in TRAIN_EXAMPLES:
        tokens, tags = _to_bio(text, entities)
        prev_tag = "O"
        for i in range(len(tokens)):
            X_dicts.append(_features(tokens, i, prev_tag))
            y.append(tags[i])
            prev_tag = tags[i]  # gold tag during training ("teacher forcing")
    return X_dicts, y


# ---------------------------------------------------------------------
# Train once at import time (fast: ~40 short sentences). For real
# deployment, train offline and pickle _vectorizer + _clf to disk
# instead of retraining on every process start.
# ---------------------------------------------------------------------

_X_dicts, _y = _build_training_set()
_vectorizer = DictVectorizer(sparse=True)
_X = _vectorizer.fit_transform(_X_dicts)
_clf = LogisticRegression(max_iter=1000, class_weight="balanced")
_clf.fit(_X, _y)


def detect_ner(text: str) -> List[Span]:
    tokens = tokenize(text)
    if not tokens:
        return []

    preds = []
    prev_tag = "O"
    for i in range(len(tokens)):
        feat = _features(tokens, i, prev_tag)
        tag = _clf.predict(_vectorizer.transform([feat]))[0]
        if tokens[i][0].lower() in _NEVER_ENTITY:
            tag = "O"  # override: these can never be an entity
        preds.append(tag)
        prev_tag = tag  # greedy: feed our own prediction forward

    spans, cur_label, cur_start, cur_end = [], None, None, None
    for (word, start, end), tag in zip(tokens, preds):
        if tag == "O":
            if cur_label:
                spans.append(Span(cur_label, cur_start, cur_end, text[cur_start:cur_end]))
                cur_label = None
            continue
        prefix, label = tag.split("-", 1)
        if prefix == "B" or label != cur_label:
            if cur_label:
                spans.append(Span(cur_label, cur_start, cur_end, text[cur_start:cur_end]))
            cur_label, cur_start, cur_end = label, start, end
        else:
            cur_end = end
    if cur_label:
        spans.append(Span(cur_label, cur_start, cur_end, text[cur_start:cur_end]))
    return spans


if __name__ == "__main__":
    # sanity check on sentences NOT in the training set, to show this
    # generalizes rather than just memorizing
    tests = [
        "Hello, this is Kabir Malhotra calling about my insurance with Star Union Bank.",
        "I was referred here by Dr. Ritu Bansal from Sunrise Medical College.",
        "Please connect me with Global Tech Systems support.",
    ]
    for t in tests:
        print(t)
        for s in detect_ner(t):
            print("   ", s.entity_type, "->", s.value)
        print()
