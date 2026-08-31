import { Link } from "react-router-dom";

export function UnauthorizedPage() {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "0.75rem",
        padding: "1.5rem",
        textAlign: "center",
      }}
    >
      <h1 style={{ fontSize: "1.3rem" }}>Not authorized</h1>
      <p style={{ color: "var(--color-text-secondary)", maxWidth: "320px" }}>
        You don't have permission to view this page. If you believe this is
        a mistake, contact your administrator.
      </p>
      <Link to="/login" style={{ marginTop: "0.5rem" }}>
        Return to login
      </Link>
    </div>
  );
}