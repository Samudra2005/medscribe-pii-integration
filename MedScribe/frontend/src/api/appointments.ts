import { apiRequest } from "./client";
import type { Appointment, CreateAppointmentPayload } from "../types/appointment";

export function createAppointment(payload: CreateAppointmentPayload): Promise<Appointment> {
  return apiRequest<Appointment>("/appointments", { method: "POST", body: payload });
}

export function listAppointments(patientId?: string): Promise<Appointment[]> {
  return apiRequest<Appointment[]>("/appointments", { params: { patient_id: patientId } });
}

export function getAppointment(id: string): Promise<Appointment> {
  return apiRequest<Appointment>(`/appointments/${id}`);
}