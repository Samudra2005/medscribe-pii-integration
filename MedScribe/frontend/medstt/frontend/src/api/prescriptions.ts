import { apiRequest } from "./client";
import type { Prescription, PrescriptionData } from "../types/prescription";
export function getPrescription(id:string){return apiRequest<Prescription>(`/prescriptions/${id}`)}
export function updatePrescription(id:string, formData:PrescriptionData){return apiRequest<Prescription>(`/prescriptions/${id}`,{method:"PATCH",body:{form_data:formData}})}
export function finalizePrescription(id:string){return apiRequest<Prescription>(`/prescriptions/${id}/finalize`,{method:"POST"})}
