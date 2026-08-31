import { apiRequest } from "./client";
import type { Patient, CreatePatientPayload, UpdatePatientPayload } from "../types/patient";

export function listPatients(search?: string): Promise<Patient[]> {
  return apiRequest<Patient[]>("/patients", { params: { search } });
}

export function getPatient(id: string): Promise<Patient> {
  return apiRequest<Patient>(`/patients/${id}`);
}

export function createPatient(payload: CreatePatientPayload): Promise<Patient> {
  return apiRequest<Patient>("/patients", { method: "POST", body: payload });
}

export function updatePatient(
  id: string,
  payload: UpdatePatientPayload
): Promise<Patient> {
  return apiRequest<Patient>(`/patients/${id}`, { method: "PATCH", body: payload });
}

export function deletePatient(id: string): Promise<void> {
  return apiRequest<void>(`/patients/${id}`, { method: "DELETE" });
}