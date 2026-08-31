export type RecordingStage = "nurse_intake" | "doctor_consultation";
export type InputSource = "uploaded_audio" | "live_recording" | "manual_entry";
export type AudioProcessingStatus =
  | "uploaded"
  | "validating"
  | "validation_failed"
  | "normalizing"
  | "chunking"
  | "chunking_complete"
  | "transcribing"
  | "transcription_complete"
  | "transcription_failed";

export interface AudioRecording {
  id: string;
  appointment_id: string;
  uploaded_by_id: string;
  input_source: InputSource;
  original_filename: string | null;
  mime_type: string | null;
  file_size_bytes: number | null;
  duration_seconds: number | null;
  processing_status: AudioProcessingStatus;
  quality_metrics: Record<string, unknown> | null;
  validation_failure_reason: string | null;
  created_at: string;
}

export interface AudioChunk {
  id: string;
  audio_recording_id: string;
  chunk_index: number;
  start_time_seconds: number;
  end_time_seconds: number;
  overlap_seconds: number;
  speaker_label: string | null;
  storage_path: string;
}