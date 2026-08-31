import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import type { UserRole } from "../types/user";
import styles from "./AppShell.module.css";

interface NavItem {
  label: string;
  to: string;
}

const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Administrator",
  nurse: "Nurse",
  doctor: "Doctor",
};

const ROLE_NAV_ITEMS: Record<UserRole, NavItem[]> = {
  admin: [
    { label: "Overview", to: "/admin" },
    { label: "Patients", to: "/admin/patients" },
    { label: "Users", to: "/admin/users" },
    { label: "HITL Queue", to: "/admin/hitl" },
    { label: "Audit Log", to: "/admin/audit-logs" },
  ],
  nurse: [
    { label: "Overview", to: "/nurse" },
    { label: "Patients", to: "/nurse/patients" },
  ],
  doctor: [
    { label: "Overview", to: "/doctor" },
    { label: "Patients", to: "/doctor/patients" },
  ],
};

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const { user, logout } = useAuth();

  if (!user) return null; // ProtectedRoute guarantees this won't happen in practice

  const roleAccentVar = `var(--color-role-${user.role})`;
  const navItems = ROLE_NAV_ITEMS[user.role];

  return (
    <div className={styles.shell}>
      <aside className={styles.sidebar}>
        <div className={styles.roleAccent} style={{ backgroundColor: roleAccentVar }} />
        <div className={styles.brand}>
          <div className={styles.brandName}>MedSTT</div>
          <div className={styles.brandRole} style={{ color: roleAccentVar }}>
            {ROLE_LABELS[user.role]}
          </div>
        </div>
        <nav className={styles.nav}>
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === `/${user.role}`}
              className={({ isActive }) =>
                isActive ? `${styles.navLink} ${styles.navLinkActive}` : styles.navLink
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>

      <div className={styles.main}>
        <header className={styles.topbar}>
          <div />
          <div className={styles.userInfo}>
            <div style={{ textAlign: "right" }}>
              <div className={styles.userName}>{user.full_name}</div>
              <div className={styles.userUsername}>@{user.username}</div>
            </div>
            <button className={styles.logoutButton} onClick={() => logout()}>
              Log out
            </button>
          </div>
        </header>
        <main className={styles.content}>{children}</main>
      </div>
    </div>
  );
}