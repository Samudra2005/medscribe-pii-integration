"""
Parses MedGemma's structured prose output into PrescriptionData.

REBUILT after real-data testing revealed the first version's parsing
was fragile: matching section names ANYWHERE in the text (not just as
real markdown headings) caused the word "symptoms" inside a Problem
Summary sentence to be mistaken for the Symptoms heading, truncating
that section. Also, medications were requested as their own
"**Medication:**" heading with items BELOW it as bullets (not inline on
the same line as first assumed), which the original medication regex
didn't handle at all -- confirmed by real output containing a clear
Medication section that the old parser completely missed.

Now works line-by-line: each line is checked against whether it IS a
heading (matches a known section name at the start of a stripped,
markdown-stripped line), not whether it CONTAINS the section name
anywhere. This is fundamentally more robust against section names
appearing incidentally within prose content.
"""
import re

from app.schemas.prescription import MedicationOrder, PrescriptionData

# Order matters only for readability here -- matching is heading-based,
# not position-based, unlike the previous version.
SECTION_HEADINGS = {
    "problem_summary": "problem summary",
    "symptoms": "symptoms",
    "existing_conditions": "existing conditions",
    "advice": "advice",
    "follow_up": "follow up",
    "medications": "medication",  # singular prefix matches "Medication:" or "Medications:"
}


def _strip_markdown(line: str) -> str:
    # Removes leading bullet markers and bold markers (**text**) so a
    # line like "**Problem Summary:**" or "*   Diarrhea" can be matched
    # cleanly against plain section names.
    line = re.sub(r"^\*+\s*", "", line)  # leading bullet/bold asterisks
    line = re.sub(r"\*+$", "", line)      # trailing bold asterisks
    return line.strip()


def _match_heading(stripped_line: str) -> str | None:
    """
    Returns the section key if this line IS a heading line (starts with
    a known section name, optionally followed by a colon and nothing
    else substantial), or None if it's ordinary content. This is the
    key fix: "Patient presents with symptoms including..." does NOT
    match, because "symptoms" isn't at the START of the line followed
    immediately by end-of-line/colon -- but "Symptoms:" does match.
    """
    lowered = stripped_line.lower().rstrip(":").strip()
    for key, heading_text in SECTION_HEADINGS.items():
        if lowered == heading_text:
            return key
    return None


def _parse_sections(raw_text: str) -> dict[str, list[str]]:
    """
    Single pass through the text, line by line. Every line is either a
    heading (switches which section subsequent lines belong to) or
    content (appended to whichever section is currently active).
    Content before the first recognized heading is discarded (typically
    just a title line like "**Clinical Intake Summary**").
    """
    sections: dict[str, list[str]] = {key: [] for key in SECTION_HEADINGS}
    current_section: str | None = None

    for raw_line in raw_text.split("\n"):
        stripped = _strip_markdown(raw_line)
        if not stripped:
            continue

        heading_key = _match_heading(stripped)
        if heading_key:
            current_section = heading_key
            continue

        if current_section:
            sections[current_section].append(stripped)

    return sections


def parse_medgemma_draft_to_prescription(
    raw_text: str,
    model_name: str,
    model_version: str,
) -> PrescriptionData:
    sections = _parse_sections(raw_text)

    problem_summary = sections["problem_summary"][0] if sections["problem_summary"] else ""

    medications = [
        MedicationOrder(name=line) for line in sections["medications"]
    ]

    return PrescriptionData(
        problem_summary=problem_summary,
        symptoms=sections["symptoms"],
        existing_conditions=sections["existing_conditions"],
        medications=medications,
        advice=sections["advice"],
        follow_up=sections["follow_up"],
        ai_generated=True,
        ai_model_name=model_name,
        ai_model_version=model_version,
        ai_raw_draft_text=raw_text,
    )