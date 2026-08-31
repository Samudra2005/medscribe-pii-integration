import { AppShell } from "../components/AppShell";
import { useAuth } from "../context/AuthContext";

export function AdminDashboard() {
  const { user } = useAuth();

  return (
    <AppShell>
      <h1>Overview</h1>
      <p style={{ color: "var(--color-text-secondary)", marginTop: "0.5rem" }}>
        Welcome back, {user?.full_name}. This is the administrator overview —
        patient records, user management, HITL review, and the audit trail
        are available in the sidebar.
      </p>
    </AppShell>
  );
}