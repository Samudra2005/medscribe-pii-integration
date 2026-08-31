import { apiRequest } from "./client";
import type { IntakeForm, IntakeFormData } from "../types/intakeForm";

export function createIntakeForm(appointmentId: string, formData: IntakeFormData): Promise<IntakeForm> {
  return apiRequest<IntakeForm>("/intake-forms", {
    method: "POST",
    body: { appointment_id: appointmentId, form_data: formData },
  });
}
export function draftIntakeForm(appointmentId: string): Promise<IntakeForm> {
  return apiRequest<IntakeForm>(`/intake-forms/appointments/${appointmentId}/draft`, { method: "POST" });
}
export function getIntakeForm(id: string): Promise<IntakeForm> {
  return apiRequest<IntakeForm>(`/intake-forms/${id}`);
}
export function updateIntakeForm(id: string, formData: IntakeFormData): Promise<IntakeForm> {
  return apiRequest<IntakeForm>(`/intake-forms/${id}`, { method: "PATCH", body: formData });
}
export function finalizeIntakeForm(id: string): Promise<IntakeForm> {
  return apiRequest<IntakeForm>(`/intake-forms/${id}/finalize`, { method: "POST" });
}
