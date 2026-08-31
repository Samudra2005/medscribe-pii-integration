// Mirrors app/models/enums.py AuditAction and schemas/audit.py AuditLogEntry.

export type AuditAction =
  | "login_success"
  | "login_failed"
  | "logout"
  | "create"
  | "read"
  | "update"
  | "delete"
  | "soft_delete"
  | "approve"
  | "reject"
  | "edit_ai_output"
  | "export_pdf"
  | "hitl_resolve";

export interface AuditLogEntry {
    
  id: string;
  occurred_at: string;
  actor_user_id: string | null;
  actor_role: string | null;
  action: AuditAction;
  target_entity_type: string | null;
  target_entity_id: string | null;
  ip_address: string | null;
  metadata_json: Record<string, unknown> | null;
  success: boolean;
}