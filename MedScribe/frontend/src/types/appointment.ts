// Mirrors schemas/appointment.py AppointmentSummary + enums.py AppointmentStatus.

export type AppointmentStatus =
  | "created"
  | "intake_in_progress"
  | "intake_complete"
  | "with_doctor"
  | "prescription_complete"
  | "complete";

export interface Appointment {
  id: string;
  patient_id: string;
  nurse_id: string;
  doctor_id: string | null;
  status: AppointmentStatus;
  chief_complaint: string | null;
  scheduled_at: string | null;
  intake_completed_at: string | null;
  prescription_completed_at: string | null;
  created_at: string;
}

export interface CreateAppointmentPayload {
  patient_id: string;
  chief_complaint?: string;
  scheduled_at?: string;
}