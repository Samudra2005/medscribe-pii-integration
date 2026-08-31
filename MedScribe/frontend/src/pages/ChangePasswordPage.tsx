import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import * as authApi from "../api/auth";
import { ApiError } from "../api/client";
import styles from "./LoginPage.module.css";

export function ChangePasswordPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (newPassword !== confirmPassword) {
      setError("New password and confirmation do not match.");
      return;
    }

    setIsSubmitting(true);
    try {
      await authApi.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      });
      // Backend revokes ALL sessions (including this one) on password
      // change -- so we treat the user as logged out and force a fresh
      // login, rather than trying to carry the old session forward.
      await logout().catch(() => {
        // Expected to fail (401) since the session is already dead
        // server-side by this point.
      });
      navigate("/login", {
        replace: true,
        state: { message: "Password changed. Please log in again." },
      });
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.detail);
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.brand}>
          <div className={styles.brandName}>MedSTT</div>
          <div className={styles.brandTagline}>Set a new password to continue</div>
        </div>

        {error && <div className={styles.errorBanner}>{error}</div>}

        <p style={{ fontSize: "0.85rem", color: "var(--color-text-secondary)", marginBottom: "1.1rem" }}>
          Signed in as <strong>{user?.username}</strong>. Your temporary
          password must be changed before you can continue.
        </p>

        <form onSubmit={handleSubmit}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="current_password">
              Current (temporary) password
            </label>
            <input
              id="current_password"
              className={styles.input}
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="new_password">
              New password
            </label>
            <input
              id="new_password"
              className={styles.input}
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={12}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="confirm_password">
              Confirm new password
            </label>
            <input
              id="confirm_password"
              className={styles.input}
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={12}
            />
          </div>
          <button className={styles.submitButton} type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Saving..." : "Change password"}
          </button>
        </form>
      </div>
    </div>
  );
}