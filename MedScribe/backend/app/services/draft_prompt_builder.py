"""
Builds the actual prompt sent to MedGemma from real appointment data:
accepted (validated) transcript text + accepted (validated) entities
from Phase 10-12's pipeline. Deliberately does NOT include rejected
entities or low-confidence transcript segments -- only material that
already passed this project's own validation gates should be presented
to MedGemma as ground truth to draft from.
"""
from app.models.extracted_entity import ExtractedEntitySet
from app.models.transcript import Transcript

SYSTEM_INSTRUCTION = (
    "You are assisting a nurse in drafting a structured clinical intake "
    "summary from a conversation transcript. Use only the information "
    "provided below. Do not invent details, dosages, durations, or "
    "diagnoses not present in the source material. If information is "
    "incomplete or ambiguous, note that explicitly rather than guessing."
)


def build_prescription_draft_prompt(
    transcripts: list[Transcript],
    entity_sets: list[ExtractedEntitySet],
) -> str:
    # Map each accepted transcript to whatever accepted entities came
    # from it specifically -- lets us filter to transcripts that
    # actually carry clinical signal, rather than including every
    # filler/scheduling/garbled fragment regardless of content.
    entities_by_transcript_id: dict = {}
    for entity_set in entity_sets:
        if not entity_set.validated_entities:
            continue
        accepted = [
            e for e in entity_set.validated_entities.get("entities", [])
            if e.get("status") == "accepted"
        ]
        if accepted:
            entities_by_transcript_id[entity_set.transcript_id] = accepted

    # Only DRAFT-status (accepted, non-flagged per Phase 10/11) AND
    # entity-bearing transcripts. This is a deliberate choice: a
    # transcript with no extracted entities is very likely filler,
    # scheduling chatter, or a garbled fragment that adds token cost and
    # noise without adding drafting value -- confirmed directly by
    # inspecting the unfiltered prompt, which was full of lines like
    # "any questions will me." and "best. Thank you. Bye." contributing
    # nothing clinically useful.
    #
    # TRADE-OFF BEING MADE EXPLICIT: this means transcripts with
    # clinically relevant content that the NER models simply MISSED
    # (a real, acknowledged limitation from Phase 12 -- e.g. the
    # "antibiotics" miss found during initial model testing) will be
    # silently excluded too. This is a real limitation, not a false
    # sense of completeness -- flagging it here rather than pretending
    # entity-based filtering is a perfect proxy for clinical relevance.
    relevant_transcripts = [
        t for t in transcripts
        if t.status.value == "draft" and t.text.strip() and t.id in entities_by_transcript_id
    ]

    all_accepted_entity_strings: list[str] = []
    for t in relevant_transcripts:
        for entity in entities_by_transcript_id[t.id]:
            label = entity.get("label", "")
            text = entity.get("text", "")
            all_accepted_entity_strings.append(f"{text} ({label})")

    # Deduplicate entity strings while preserving first-seen order --
    # the same symptom (e.g. "diarrhea") is mentioned multiple times
    # across a real conversation; the drafting prompt only needs to
    # state it once, not repeat it N times.
    seen = set()
    deduped_entities = []
    for e in all_accepted_entity_strings:
        if e not in seen:
            seen.add(e)
            deduped_entities.append(e)

    transcript_block = "\n".join(f"- \"{t.text}\"" for t in relevant_transcripts)
    entities_block = ", ".join(deduped_entities) if deduped_entities else "None extracted"

    return (
        f"{SYSTEM_INSTRUCTION}\n\n"
        f"Transcript excerpts:\n{transcript_block}\n\n"
        f"Extracted entities (validated, high-confidence): {entities_block}\n\n"
        f"Draft a brief structured clinical note with these exact sections: "
        f"Problem Summary, Symptoms, Existing Conditions, Advice, Follow Up. "
        f"For medications, list each on its own line starting with 'Medication:' "
        f"followed by the name and any stated dosage/frequency/duration. "
        f"Keep it concise."
    )