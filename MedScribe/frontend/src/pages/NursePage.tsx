import { AppShell } from "../components/AppShell";
import { useAuth } from "../context/AuthContext";

export function NursePage() {
  const { user } = useAuth();

  return (
    <AppShell>
      <h1>Overview</h1>
      <p style={{ color: "var(--color-text-secondary)", marginTop: "0.5rem" }}>
        Welcome back, {user?.full_name}. Patient intake and appointment
        tools will appear here as later phases are built.
      </p>
    </AppShell>
  );
}