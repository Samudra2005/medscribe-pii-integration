// Mirrors app/models/enums.py UserRole / UserStatus (backend).
// Kept as string literal unions, not TS enums -- these values are sent
// over the wire as plain lowercase strings ('admin', 'nurse', 'doctor'),
// and a string union matches that directly with no extra mapping step.

export type UserRole = "admin" | "nurse" | "doctor";

export type UserStatus = "active" | "suspended" | "deactivated";

// Mirrors schemas/auth.py LoginResponse.
// This is what /auth/login and /auth/me both return.
export interface CurrentUser {
  user_id: string;
  username: string;
  full_name: string;
  role: UserRole;
  must_change_password: boolean;
}

// Mirrors schemas/user.py UserSummary -- used in the admin user list view.
export interface UserSummary {
  id: string;
  username: string;
  email: string;
  full_name: string;
  role: UserRole;
  status: UserStatus;
  is_locked: boolean;
  created_at: string; // ISO datetime string; format for display where used
}

// Mirrors schemas/user.py CreateUserResponse.
export interface CreateUserResponse {
  user_id: string;
  username: string;
  temporary_password: string;
}