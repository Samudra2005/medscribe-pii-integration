// Mirrors app/models/enums.py HitlReason / HitlStatus and schemas/hitl.py.

export type HitlReason =
  | "low_asr_confidence"
  | "hallucination_suspected"
  | "omission_suspected"
  | "consensus_mismatch"
  | "ner_validation_failed"
  | "schema_validation_failed"
  | "manual_flag";

export type HitlStatus = "pending" | "in_review" | "resolved" | "dismissed";

export interface HitlItem {
  id: string;
  appointment_id: string;
  transcript_id: string | null;
  entity_set_id: string | null;
  reason: HitlReason;
  status: HitlStatus;
  user_facing_message: string;
  detail: Record<string, unknown> | null;
  assigned_admin_id: string | null;
  resolved_by_id: string | null;
  resolution_notes: string | null;
  resolved_at: string | null;
  created_at: string;
}

export interface ResolveHitlPayload {
  resolution_notes: string;
  dismiss: boolean;
}

// Human-readable labels -- kept separate from the wire values so display
// text can be improved without touching anything that talks to the API.
export const HITL_REASON_LABELS: Record<HitlReason, string> = {
  low_asr_confidence: "Low ASR confidence",
  hallucination_suspected: "Hallucination suspected",
  omission_suspected: "Omission suspected",
  consensus_mismatch: "Consensus mismatch",
  ner_validation_failed: "NER validation failed",
  schema_validation_failed: "Schema validation failed",
  manual_flag: "Manually flagged",
};