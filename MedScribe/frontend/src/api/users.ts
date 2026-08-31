import { apiRequest } from "./client";
import type { UserSummary, CreateUserResponse, UserRole, UserStatus } from "../types/user";

export interface CreateUserPayload {
  username: string;
  email: string;
  full_name: string;
  role: UserRole;
}

export function listUsers(): Promise<UserSummary[]> {
  return apiRequest<UserSummary[]>("/admin/users");
}

export function getUser(id: string): Promise<UserSummary> {
  return apiRequest<UserSummary>(`/admin/users/${id}`);
}

export function createUser(payload: CreateUserPayload): Promise<CreateUserResponse> {
  return apiRequest<CreateUserResponse>("/admin/users", { method: "POST", body: payload });
}

export function updateUserStatus(
  id: string,
  status: UserStatus
): Promise<UserSummary> {
  return apiRequest<UserSummary>(`/admin/users/${id}/status`, {
    method: "PATCH",
    body: { status },
  });
}