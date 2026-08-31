"""
Generates the final prescription PDF at finalization time. Only ever
called on an already-finalized Prescription (is_final=True) -- a draft
should never have a PDF, matching the model's own nullable
pdf_storage_path design intent ("nullable until finalization").
"""
import uuid
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.config import get_settings
from app.core.logging_config import get_logger
from app.models.appointment import Appointment
from app.models.patient import Patient
from app.models.prescription import Prescription
from app.models.user import User
from app.schemas.prescription import PrescriptionData

logger = get_logger(__name__)
settings = get_settings()


def _pdf_storage_dir() -> Path:
    # Mirrors the storage/audio/... convention from Phase 7 -- relative
    # to AUDIO_STORAGE_ROOT's parent (storage/), not reusing the audio
    # subtree itself since prescriptions aren't audio artifacts.
    return Path(settings.AUDIO_STORAGE_ROOT).parent / "prescriptions"


def _build_pdf(
    output_path: Path,
    patient: Patient,
    doctor: User,
    appointment: Appointment,
    prescription: Prescription,
    data: PrescriptionData,
) -> None:
    styles = getSampleStyleSheet()
    header_style = ParagraphStyle("ClinicHeader", parent=styles["Title"], fontSize=16, spaceAfter=4)
    section_style = ParagraphStyle("Section", parent=styles["Heading2"], spaceBefore=12, spaceAfter=4)
    body_style = styles["Normal"]
    disclaimer_style = ParagraphStyle(
        "Disclaimer", parent=styles["Normal"], fontSize=8, textColor="#666666", spaceBefore=20
    )

    story = []

    story.append(Paragraph("MedSTT Clinical Prescription", header_style))
    story.append(Spacer(1, 8))

    patient_table_data = [
        ["Patient:", patient.full_name, "MRN:", patient.mrn],
        ["Date of Birth:", patient.date_of_birth.isoformat(), "Sex:", patient.sex],
        ["Prescribing Doctor:", doctor.full_name, "Date Finalized:", prescription.finalized_at.strftime("%Y-%m-%d %H:%M") if prescription.finalized_at else "—"],
    ]
    patient_table = Table(patient_table_data, colWidths=[1.3 * inch, 2.2 * inch, 1.3 * inch, 1.7 * inch])
    patient_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(patient_table)
    story.append(Spacer(1, 12))

    story.append(Paragraph("Problem Summary", section_style))
    story.append(Paragraph(data.problem_summary or "Not specified.", body_style))

    if data.symptoms:
        story.append(Paragraph("Symptoms", section_style))
        for s in data.symptoms:
            story.append(Paragraph(f"• {s}", body_style))

    if data.existing_conditions:
        story.append(Paragraph("Existing Conditions", section_style))
        for c in data.existing_conditions:
            story.append(Paragraph(f"• {c}", body_style))

    if data.medications:
        story.append(Paragraph("Medications", section_style))
        med_rows = [["Medication", "Dosage", "Frequency", "Duration"]]
        for m in data.medications:
            med_rows.append([m.name, m.dosage or "—", m.frequency or "—", m.duration or "—"])
        med_table = Table(med_rows, colWidths=[2.3 * inch, 1.4 * inch, 1.4 * inch, 1.4 * inch])
        med_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("BACKGROUND", (0, 0), (-1, 0), "#EEEEEE"),
                    ("GRID", (0, 0), (-1, -1), 0.5, "#CCCCCC"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(med_table)

    if data.advice:
        story.append(Paragraph("Advice", section_style))
        for a in data.advice:
            story.append(Paragraph(f"• {a}", body_style))

    if data.follow_up:
        story.append(Paragraph("Follow-up", section_style))
        for f in data.follow_up:
            story.append(Paragraph(f"• {f}", body_style))

    # Explicit AI-provenance disclosure on the final document itself --
    # not just in the DB record. If any part of this prescription was
    # AI-drafted at any point, the printed/PDF record says so, matching
    # both MedASR's and MedGemma's own model card requirement that
    # outputs "require independent verification" and never be presented
    # as if a human authored them without disclosure.
    if data.ai_generated:
        story.append(
            Paragraph(
                f"This document was drafted with AI assistance ({data.ai_model_name or 'unknown model'}) "
                f"and has been reviewed and approved by the prescribing doctor named above. "
                f"AI-generated content requires independent clinical verification and should not "
                f"be considered a substitute for professional medical judgment.",
                disclaimer_style,
            )
        )

    doc = SimpleDocTemplate(str(output_path), pagesize=letter, topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    doc.build(story)


async def generate_prescription_pdf(
    prescription: Prescription,
    patient: Patient,
    doctor: User,
    appointment: Appointment,
) -> str:
    """
    Returns the RELATIVE storage path, same convention as Phase 7's
    audio storage. Only call this on an already is_final=True
    prescription -- caller's responsibility (enforced at the API layer,
    not re-checked here, to keep this function focused purely on PDF
    generation mechanics).
    """
    import asyncio

    data = PrescriptionData(**prescription.form_data)

    storage_dir = _pdf_storage_dir()
    await asyncio.to_thread(storage_dir.mkdir, parents=True, exist_ok=True)

    filename = f"{prescription.id}.pdf"
    output_path = storage_dir / filename

    await asyncio.to_thread(_build_pdf, output_path, patient, doctor, appointment, prescription, data)

    relative_path = f"prescriptions/{filename}"
    logger.info("prescription_pdf_generated", prescription_id=str(prescription.id), path=relative_path)
    return relative_path