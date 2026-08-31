// Mirrors schemas/patient.py exactly.

export interface Patient {
  id: string;
  mrn: string;
  full_name: string;
  date_of_birth: string; // ISO date (YYYY-MM-DD)
  sex: string;
  phone_number: string | null;
  address: string | null;
  known_allergies: string | null;
  created_at: string; // ISO datetime
  created_by_id: string;
}

export interface CreatePatientPayload {
  mrn: string;
  full_name: string;
  date_of_birth: string; // YYYY-MM-DD
  sex: string;
  phone_number?: string;
  address?: string;
  known_allergies?: string;
}

export interface UpdatePatientPayload {
  full_name?: string;
  phone_number?: string;
  address?: string;
  known_allergies?: string;
}