import { apiRequest } from "./client";
import type { HitlItem, HitlStatus, ResolveHitlPayload } from "../types/hitl";

export function listHitlItems(statusFilter?: HitlStatus): Promise<HitlItem[]> {
  return apiRequest<HitlItem[]>("/admin/hitl", {
    params: { status_filter: statusFilter },
  });
}

export function claimHitlItem(id: string): Promise<HitlItem> {
  return apiRequest<HitlItem>(`/admin/hitl/${id}/claim`, { method: "POST" });
}

export function resolveHitlItem(
  id: string,
  payload: ResolveHitlPayload
): Promise<HitlItem> {
  return apiRequest<HitlItem>(`/admin/hitl/${id}/resolve`, {
    method: "POST",
    body: payload,
  });
}