import { apiRequest } from "./client";
import type { AudioRecording, AudioChunk } from "../types/audio";
import type { TranscriptWithQuality, ExtractedEntitySetFull } from "../types/transcriptExtended";
import type { Prescription } from "../types/prescription";

export function uploadAudioFile(
  appointmentId: string,
  file: File,
  recordingStage: "nurse_intake" | "doctor_consultation"
): Promise<AudioRecording> {
  const formData = new FormData();
  formData.append("appointment_id", appointmentId);
  formData.append("file", file);
  formData.append("recording_stage", recordingStage);
  return apiRequestMultipart<AudioRecording>("/audio/upload", formData);
}

export function uploadLiveRecording(
  appointmentId: string,
  blob: Blob,
  recordingStage: "nurse_intake" | "doctor_consultation"
): Promise<AudioRecording> {
  const formData = new FormData();
  formData.append("appointment_id", appointmentId);
  formData.append("file", blob, "live_recording.webm");
  formData.append("recording_stage", recordingStage);
  return apiRequestMultipart<AudioRecording>("/audio/record", formData);
}

// multipart/form-data needs its own fetch call -- apiRequest's JSON-only
// body handling (Content-Type: application/json, JSON.stringify) isn't
// appropriate for FormData, which needs the browser to set its own
// multipart boundary header automatically.
async function apiRequestMultipart<T>(path: string, formData: FormData): Promise<T> {
  const API_BASE_URL = import.meta.env.VITE_API_BASE_URL;
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    credentials: "include",
    body: formData,
  });
  const data = await response.json();
  if (!response.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? String(data.detail) : "Upload failed";
    throw new Error(detail);
  }
  return data as T;
}

export function listRecordings(appointmentId: string): Promise<AudioRecording[]> {
  return apiRequest<AudioRecording[]>("/audio", { params: { appointment_id: appointmentId } });
}

export function chunkRecording(recordingId: string): Promise<AudioChunk[]> {
  return apiRequest<AudioChunk[]>(`/audio/${recordingId}/chunk`, { method: "POST" });
}

export function listChunks(recordingId: string): Promise<AudioChunk[]> {
  return apiRequest<AudioChunk[]>(`/audio/${recordingId}/chunks`);
}

export function transcribeRecording(recordingId: string): Promise<TranscriptWithQuality[]> {
  return apiRequest<TranscriptWithQuality[]>(`/audio/${recordingId}/transcribe`, { method: "POST" });
}

export function listTranscripts(recordingId: string): Promise<TranscriptWithQuality[]> {
  return apiRequest<TranscriptWithQuality[]>(`/audio/${recordingId}/transcripts`);
}

export function extractEntities(recordingId: string): Promise<ExtractedEntitySetFull[]> {
  return apiRequest<ExtractedEntitySetFull[]>(`/audio/${recordingId}/extract-entities`, { method: "POST" });
}

export function listEntities(recordingId: string): Promise<ExtractedEntitySetFull[]> {
  return apiRequest<ExtractedEntitySetFull[]>(`/audio/${recordingId}/entities`);
}

export function draftPrescription(appointmentId: string): Promise<Prescription> {
  return apiRequest<Prescription>(`/audio/appointments/${appointmentId}/draft-prescription`, { method: "POST" });
}