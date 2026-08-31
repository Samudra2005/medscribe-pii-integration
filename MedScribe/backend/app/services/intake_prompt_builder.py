"""
Builds a prompt asking MedGemma to extract vitals/prior-test mentions
from NURSE_INTAKE-stage transcripts specifically (not doctor-
consultation transcripts -- see AudioRecording.recording_stage, added
specifically to support this real two-recording clinical workflow).

REBUILT after a real failure: MedGemma's first version of this prompt
misclassified "six seven times a day" (bowel movement frequency, from
context) as a pulse rate reading -- a genuinely dangerous
misclassification if trusted uncritically. Root cause: the original
prompt asked for a vital sign VALUE without requiring MedGemma to also
show the exact source phrase it based that value on, making it easy for
a stray number near vitals-related vocabulary to get mis-attributed.
FIX: now requires MedGemma to quote the EXACT source sentence it is
extracting from alongside each value, and explicitly warns against the
observed failure mode (numbers describing frequency/duration/dosage
being confused for vital sign readings) -- forcing traceability makes
a wrong extraction visible and checkable by a human, rather than a
bare, unverifiable number.
"""
from app.models.transcript import Transcript

SYSTEM_INSTRUCTION = (
    "You are assisting a nurse in identifying vital signs or prior test "
    "orders/results that were EXPLICITLY STATED, as actual measurements, "
    "in the conversation transcript below. Only extract a value if you "
    "can quote the EXACT sentence it came from. Do NOT extract a number "
    "just because it appears near vitals-related words -- a number "
    "describing how often something happens (e.g. 'six times a day'), "
    "how long a dose lasts, or any other non-measurement context is NOT "
    "a vital sign, even if it superficially resembles one. If no vital "
    "sign or prior test information was explicitly stated as a "
    "measurement, you MUST say 'Not mentioned' for that field -- do not "
    "guess, estimate, or repurpose an unrelated number."
)


def build_intake_extraction_prompt(transcripts: list[Transcript]) -> str:
    relevant_texts = [t.text for t in transcripts if t.status.value == "draft" and t.text.strip()]
    transcript_block = "\n".join(f"- \"{t}\"" for t in relevant_texts)

    return (
        f"{SYSTEM_INSTRUCTION}\n\n"
        f"Transcript excerpts:\n{transcript_block}\n\n"
        f"For EACH field below, respond with either 'Not mentioned', or the "
        f"value followed by the exact quoted source sentence in parentheses. "
        f"Example format: 'Blood Pressure: 120/80 (\"her blood pressure was "
        f"one twenty over eighty\")' or 'Blood Pressure: Not mentioned'\n\n"
        f"Blood Pressure:\n"
        f"Height:\n"
        f"Weight:\n"
        f"Temperature:\n"
        f"Pulse:\n"
        f"Prior Tests Mentioned:"
    )