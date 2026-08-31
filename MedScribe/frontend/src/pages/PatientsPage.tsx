import { useState, useEffect, useCallback, type FormEvent } from "react";
import { AppShell } from "../components/AppShell";
import * as patientsApi from "../api/patients";
import type { Patient, CreatePatientPayload } from "../types/patient";
import { ApiError } from "../api/client";
import styles from "./PatientsPage.module.css";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function PatientsPage() {
  const [patients, setPatients] = useState<Patient[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState("");
  const [isCreateOpen, setIsCreateOpen] = useState(false);

  const loadPatients = useCallback(async (search?: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await patientsApi.listPatients(search || undefined);
      setPatients(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to load patients.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadPatients();
  }, [loadPatients]);

  // Debounce search -- avoid firing a request on every keystroke, which
  // would be wasteful and could visibly lag on the constrained dev
  // machine under load from the ML pipeline later on.
  useEffect(() => {
    const timeout = setTimeout(() => {
      loadPatients(searchInput);
    }, 350);
    return () => clearTimeout(timeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchInput]);

  function handlePatientCreated(patient: Patient) {
    setIsCreateOpen(false);
    setPatients((prev) => [patient, ...prev]);
  }

  return (
    <AppShell>
      <div className={styles.header}>
        <div>
          <h1>Patients</h1>
        </div>
        <div style={{ display: "flex", gap: "0.75rem", flex: 1, justifyContent: "flex-end" }}>
          <input
            className={styles.searchInput}
            type="text"
            placeholder="Search by name or MRN..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
          <button className={styles.primaryButton} onClick={() => setIsCreateOpen(true)}>
            + New Patient
          </button>
        </div>
      </div>

      {error && <div className={styles.errorBanner}>{error}</div>}

      <div className={styles.card}>
        {isLoading ? (
          <div className={styles.loadingState}>Loading patients...</div>
        ) : patients.length === 0 ? (
          <div className={styles.emptyState}>
            {searchInput
              ? `No patients match "${searchInput}".`
              : "No patients registered yet. Click \"New Patient\" to add one."}
          </div>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Name</th>
                <th>MRN</th>
                <th>Date of birth</th>
                <th>Sex</th>
                <th>Phone</th>
                <th>Registered</th>
              </tr>
            </thead>
            <tbody>
              {patients.map((p) => (
                <tr key={p.id}>
                  <td>{p.full_name}</td>
                  <td className={styles.mrn}>{p.mrn}</td>
                  <td>{formatDate(p.date_of_birth)}</td>
                  <td>{p.sex}</td>
                  <td>{p.phone_number || "—"}</td>
                  <td>{formatDate(p.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {isCreateOpen && (
        <CreatePatientModal
          onClose={() => setIsCreateOpen(false)}
          onCreated={handlePatientCreated}
        />
      )}
    </AppShell>
  );
}

interface CreatePatientModalProps {
  onClose: () => void;
  onCreated: (patient: Patient) => void;
}

function CreatePatientModal({ onClose, onCreated }: CreatePatientModalProps) {
  const [form, setForm] = useState<CreatePatientPayload>({
    mrn: "",
    full_name: "",
    date_of_birth: "",
    sex: "",
    phone_number: "",
    address: "",
    known_allergies: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function updateField<K extends keyof CreatePatientPayload>(
    field: K,
    value: CreatePatientPayload[K]
  ) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      // Strip empty-string optional fields so we send undefined rather
      // than "" to the backend -- Pydantic's Optional fields expect
      // omission or null, not empty strings, for a clean payload.
      const payload: CreatePatientPayload = {
        mrn: form.mrn,
        full_name: form.full_name,
        date_of_birth: form.date_of_birth,
        sex: form.sex,
        phone_number: form.phone_number || undefined,
        address: form.address || undefined,
        known_allergies: form.known_allergies || undefined,
      };
      const patient = await patientsApi.createPatient(payload);
      onCreated(patient);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to create patient.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <h2 style={{ fontSize: "1.1rem" }}>New Patient</h2>
          <button className={styles.closeButton} onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        {error && <div className={styles.errorBanner}>{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className={styles.formGrid}>
            <div className={`${styles.formField} ${styles.formFieldFull}`}>
              <label className={styles.label} htmlFor="full_name">
                Full name
              </label>
              <input
                id="full_name"
                className={styles.input}
                value={form.full_name}
                onChange={(e) => updateField("full_name", e.target.value)}
                required
              />
            </div>

            <div className={styles.formField}>
              <label className={styles.label} htmlFor="mrn">
                MRN
              </label>
              <input
                id="mrn"
                className={styles.input}
                value={form.mrn}
                onChange={(e) => updateField("mrn", e.target.value)}
                required
              />
            </div>

            <div className={styles.formField}>
              <label className={styles.label} htmlFor="sex">
                Sex
              </label>
              <input
                id="sex"
                className={styles.input}
                value={form.sex}
                onChange={(e) => updateField("sex", e.target.value)}
                required
              />
            </div>

            <div className={styles.formField}>
              <label className={styles.label} htmlFor="date_of_birth">
                Date of birth
              </label>
              <input
                id="date_of_birth"
                type="date"
                className={styles.input}
                value={form.date_of_birth}
                onChange={(e) => updateField("date_of_birth", e.target.value)}
                required
              />
            </div>

            <div className={styles.formField}>
              <label className={styles.label} htmlFor="phone_number">
                Phone number
              </label>
              <input
                id="phone_number"
                className={styles.input}
                value={form.phone_number}
                onChange={(e) => updateField("phone_number", e.target.value)}
              />
            </div>

            <div className={`${styles.formField} ${styles.formFieldFull}`}>
              <label className={styles.label} htmlFor="address">
                Address
              </label>
              <input
                id="address"
                className={styles.input}
                value={form.address}
                onChange={(e) => updateField("address", e.target.value)}
              />
            </div>

            <div className={`${styles.formField} ${styles.formFieldFull}`}>
              <label className={styles.label} htmlFor="known_allergies">
                Known allergies
              </label>
              <input
                id="known_allergies"
                className={styles.input}
                value={form.known_allergies}
                onChange={(e) => updateField("known_allergies", e.target.value)}
              />
            </div>
          </div>

          <div className={styles.modalActions}>
            <button type="button" className={styles.secondaryButton} onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className={styles.primaryButton} disabled={isSubmitting}>
              {isSubmitting ? "Creating..." : "Create patient"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}