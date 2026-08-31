import { apiRequest } from "./client";
import type { AuditAction, AuditLogEntry } from "../types/audit";

export interface AuditLogFilters {
    [key: string]: string | number | boolean | undefined;
  action?: AuditAction;
  actor_user_id?: string;
  target_entity_type?: string;
  target_entity_id?: string;
  success?: boolean;
  start_date?: string; // ISO datetime
  end_date?: string;
  limit?: number;
  offset?: number;
}

export function listAuditLogs(filters: AuditLogFilters = {}): Promise<AuditLogEntry[]> {
  return apiRequest<AuditLogEntry[]>("/admin/audit-logs", { params: filters });
}