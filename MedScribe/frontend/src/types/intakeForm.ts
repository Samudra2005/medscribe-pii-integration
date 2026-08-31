export interface VitalSigns {
  blood_pressure_systolic: number | null;
  blood_pressure_diastolic: number | null;
  height_cm: number | null;
  weight_kg: number | null;
  temperature_celsius: number | null;
  pulse_bpm: number | null;
}

export interface PriorTestResult {
  test_name: string;
  was_completed: boolean;
  result_summary: string | null;
}

export interface IntakeFormData {
  vitals: VitalSigns;
  prior_test_results: PriorTestResult[];
  reason_for_visit: string | null;
  known_allergies: string | null;
  ai_generated: boolean;
  ai_model_name: string | null;
  ai_model_version: string | null;
  ai_raw_draft_text: string | null;
}

export interface IntakeForm {
  id: string;
  appointment_id: string;
  nurse_id: string;
  source_entity_set_id: string | null;
  input_source: string;
  form_data: IntakeFormData;
  is_final: boolean;
  submitted_at: string | null;
  created_at: string;
}