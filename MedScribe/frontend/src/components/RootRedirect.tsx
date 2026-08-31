import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import type { UserRole } from "../types/user";

const ROLE_HOME: Record<UserRole, string> = {
  admin: "/admin",
  nurse: "/nurse",
  doctor: "/doctor",
};

/**
 * Used for "/" and the catch-all "*" route. Decides where to send a
 * visitor based on actual auth state, rather than blindly assuming
 * "not logged in" the way the old static redirect did.
 */
export function RootRedirect() {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return null;
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  if (user.must_change_password) {
    return <Navigate to="/change-password" replace />;
  }

  return <Navigate to={ROLE_HOME[user.role]} replace />;
}