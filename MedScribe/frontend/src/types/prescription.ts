export interface MedicationOrder {
  name: string;
  dosage: string | null;
  frequency: string | null;
  duration: string | null;
  instructions: string | null;
}

export interface PrescriptionData {
  problem_summary: string;
  symptoms: string[];
  existing_conditions: string[];
  medications: MedicationOrder[];
  advice: string[];
  follow_up: string[];
  ai_generated: boolean;
  ai_model_name: string | null;
  ai_model_version: string | null;
  ai_raw_draft_text: string | null;
}

export interface Prescription {
  id: string;
  appointment_id: string;
  doctor_id: string;
  source_entity_set_id: string | null;
  input_source: string;
  form_data: PrescriptionData;
  is_final: boolean;
  created_at: string;
}