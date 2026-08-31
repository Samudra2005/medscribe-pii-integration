import { apiRequest } from "./client";
import type { CurrentUser } from "../types/user";

export interface LoginPayload {
  username: string;
  password: string;
}

export interface ChangePasswordPayload {
  current_password: string;
  new_password: string;
}

export function login(payload: LoginPayload): Promise<CurrentUser> {
  return apiRequest<CurrentUser>("/auth/login", {
    method: "POST",
    body: payload,
  });
}

export function logout(): Promise<{ message: string }> {
  return apiRequest("/auth/logout", { method: "POST" });
}

export function fetchCurrentUser(): Promise<CurrentUser> {
  return apiRequest<CurrentUser>("/auth/me");
}

export function changePassword(
  payload: ChangePasswordPayload
): Promise<{ message: string }> {
  return apiRequest("/auth/change-password", {
    method: "POST",
    body: payload,
  });
}