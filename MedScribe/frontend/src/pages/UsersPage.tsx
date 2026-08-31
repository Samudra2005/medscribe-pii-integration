import { useState, useEffect, useCallback, type FormEvent } from "react";
import { AppShell } from "../components/AppShell";
import * as usersApi from "../api/users";
import type { UserSummary, UserRole, CreateUserResponse } from "../types/user";
import { ApiError } from "../api/client";
import styles from "./UsersPage.module.css";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const ROLE_BADGE_CLASS: Record<UserRole, string> = {
  admin: styles.badgeAdmin,
  nurse: styles.badgeNurse,
  doctor: styles.badgeDoctor,
};

const STATUS_CLASS: Record<string, string> = {
  active: styles.statusActive,
  suspended: styles.statusSuspended,
  deactivated: styles.statusDeactivated,
};

export function UsersPage() {
  const [users, setUsers] = useState<UserSummary[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [pendingActionId, setPendingActionId] = useState<string | null>(null);

  const loadUsers = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await usersApi.listUsers();
      setUsers(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to load users.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  async function handleStatusChange(user: UserSummary, newStatus: "active" | "suspended" | "deactivated") {
    setPendingActionId(user.id);
    setError(null);
    try {
      const updated = await usersApi.updateUserStatus(user.id, newStatus);
      setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to update user status.");
    } finally {
      setPendingActionId(null);
    }
  }

  function handleUserCreated() {
    loadUsers();
  }

  return (
    <AppShell>
      <div className={styles.header}>
        <h1>Users</h1>
        <button className={styles.primaryButton} onClick={() => setIsCreateOpen(true)}>
          + New User
        </button>
      </div>

      {error && <div className={styles.errorBanner}>{error}</div>}

      <div className={styles.card}>
        {isLoading ? (
          <div className={styles.loadingState}>Loading users...</div>
        ) : users.length === 0 ? (
          <div className={styles.emptyState}>No users found.</div>
        ) : (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Username</th>
                <th>Role</th>
                <th>Status</th>
                <th>Created</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>{u.full_name}</td>
                  <td>{u.username}</td>
                  <td>
                    <span className={`${styles.badge} ${ROLE_BADGE_CLASS[u.role]}`}>
                      {u.role}
                    </span>
                  </td>
                  <td>
                    <span className={STATUS_CLASS[u.status] ?? ""}>{u.status}</span>
                    {u.is_locked && <span className={styles.lockedTag}>locked</span>}
                  </td>
                  <td>{formatDate(u.created_at)}</td>
                  <td>
                    {u.status !== "active" && (
                      <button
                        className={styles.actionButton}
                        disabled={pendingActionId === u.id}
                        onClick={() => handleStatusChange(u, "active")}
                      >
                        Activate
                      </button>
                    )}
                    {u.status === "active" && (
                      <button
                        className={styles.actionButton}
                        disabled={pendingActionId === u.id}
                        onClick={() => handleStatusChange(u, "suspended")}
                      >
                        Suspend
                      </button>
                    )}
                    {u.status !== "deactivated" && (
                      <button
                        className={`${styles.actionButton} ${styles.dangerAction}`}
                        disabled={pendingActionId === u.id}
                        onClick={() => handleStatusChange(u, "deactivated")}
                      >
                        Deactivate
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {isCreateOpen && (
        <CreateUserModal
          onClose={() => setIsCreateOpen(false)}
          onCreated={handleUserCreated}
        />
      )}
    </AppShell>
  );
}

interface CreateUserModalProps {
  onClose: () => void;
  onCreated: () => void;
}

function CreateUserModal({ onClose, onCreated }: CreateUserModalProps) {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<UserRole>("nurse");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [createdCredentials, setCreatedCredentials] = useState<CreateUserResponse | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const result = await usersApi.createUser({
        username,
        email,
        full_name: fullName,
        role,
      });
      setCreatedCredentials(result);
      onCreated(); // refresh the list behind the modal now, not on close
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to create user.");
    } finally {
      setIsSubmitting(false);
    }
  }

  // After creation, show the one-time temp password instead of the form.
  // This is not a UX nicety -- the backend genuinely never exposes this
  // value again after this single response, per the Phase 4 design
  // ("admin never learns the user's real ongoing password"). If the
  // admin closes this dialog without noting it down, it's gone and the
  // only recovery path is a fresh account, so the copy here is intentionally
  // direct about that.
  if (createdCredentials) {
    return (
      <div className={styles.overlay} onClick={onClose}>
        <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
          <div className={styles.modalHeader}>
            <h2 style={{ fontSize: "1.1rem" }}>User created</h2>
            <button className={styles.closeButton} onClick={onClose} aria-label="Close">
              ×
            </button>
          </div>
          <p style={{ fontSize: "0.88rem", color: "var(--color-text-secondary)" }}>
            Share this temporary password with the user through a secure
            channel. They'll be required to set their own password on
            first login.
          </p>
          <div className={styles.credentialBox}>
            <div className={styles.credentialRow}>
              <span>Username</span>
              <span className={styles.credentialValue}>{createdCredentials.username}</span>
            </div>
            <div className={styles.credentialRow}>
              <span>Temporary password</span>
              <span className={styles.credentialValue}>
                {createdCredentials.temporary_password}
              </span>
            </div>
          </div>
          <p className={styles.warningNote}>
            This password will not be shown again after you close this dialog.
          </p>
          <div className={styles.modalActions}>
            <button className={styles.primaryButton} onClick={onClose}>
              Done
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
        <div className={styles.modalHeader}>
          <h2 style={{ fontSize: "1.1rem" }}>New User</h2>
          <button className={styles.closeButton} onClick={onClose} aria-label="Close">
            ×
          </button>
        </div>

        {error && <div className={styles.errorBanner}>{error}</div>}

        <form onSubmit={handleSubmit}>
          <div className={styles.formField}>
            <label className={styles.label} htmlFor="full_name">
              Full name
            </label>
            <input
              id="full_name"
              className={styles.input}
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              required
            />
          </div>
          <div className={styles.formField}>
            <label className={styles.label} htmlFor="username">
              Username
            </label>
            <input
              id="username"
              className={styles.input}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>
          <div className={styles.formField}>
            <label className={styles.label} htmlFor="email">
              Email
            </label>
            <input
              id="email"
              type="email"
              className={styles.input}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className={styles.formField}>
            <label className={styles.label} htmlFor="role">
              Role
            </label>
            <select
              id="role"
              className={styles.select}
              value={role}
              onChange={(e) => setRole(e.target.value as UserRole)}
            >
              <option value="nurse">Nurse</option>
              <option value="doctor">Doctor</option>
              <option value="admin">Admin</option>
            </select>
          </div>

          <div className={styles.modalActions}>
            <button type="button" className={styles.secondaryButton} onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className={styles.primaryButton} disabled={isSubmitting}>
              {isSubmitting ? "Creating..." : "Create user"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}