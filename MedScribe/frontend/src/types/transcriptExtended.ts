export interface QualityReportConsensus {
  outcome: string;
  similarity_ratio: number | null;
  medasr_confidence: number | null;
  azure_confidence: number | null;
  azure_text: string | null;
  azure_available: boolean;
}

export interface QualityReport {
  mean_confidence: number | null;
  min_confidence: number | null;
  word_count: number;
  words_per_second: number | null;
  repetition_detected: boolean;
  repeated_phrase: string | null;
  flags: string[];
  accept: boolean;
  consensus?: QualityReportConsensus;
}

export interface TranscriptWithQuality {
  id: string;
  appointment_id: string;
  audio_chunk_id: string | null;
  source: string;
  status: string;
  text: string;
  model_name: string;
  model_version: string | null;
  confidence_score: number | null;
  quality_report: QualityReport | null;
  created_at: string;
}

export interface ValidatedEntity {
  text: string;
  label: string;
  score: number;
  start: number;
  end: number;
  status: "accepted" | "rejected";
  rejection_reason: string | null;
}

export interface ExtractedEntitySetFull {
  id: string;
  appointment_id: string;
  transcript_id: string;
  target_role: string;
  raw_entities: { entities: ValidatedEntity[] };
  validated_entities: { entities: ValidatedEntity[]; accepted_count: number; rejected_count: number } | null;
  ner_model_name: string;
  ner_model_version: string | null;
  validation_passed: boolean | null;
  confidence_score: number | null;
  created_at: string;
}