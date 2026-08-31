import { useState, useEffect, useCallback } from "react";
import { AppShell } from "../components/AppShell";
import * as hitlApi from "../api/hitl";
import type { HitlItem, HitlStatus } from "../types/hitl";
import { HITL_REASON_LABELS } from "../types/hitl";
import { ApiError } from "../api/client";
import styles from "./HitlPage.module.css";

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const STATUS_CLASS: Record<HitlStatus, string> = {
  pending: styles.statusPending,
  in_review: styles.statusInReview,
  resolved: styles.statusResolved,
  dismissed: styles.statusDismissed,
};

type FilterOption = "actionable" | HitlStatus;

export function HitlPage() {
  const [items, setItems] = useState<HitlItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<FilterOption>("actionable");
  const [pendingActionId, setPendingActionId] = useState<string | null>(null);

  const loadItems = useCallback(async (currentFilter: FilterOption) => {
    setIsLoading(true);
    setError(null);
    try {
      // "actionable" is a frontend-only concept (pending + in_review) --
      // the backend's default (no status_filter passed) already returns
      // exactly that combination, so we omit the param in that case
      // rather than trying to pass two statuses at once.
      const statusParam = currentFilter === "actionable" ? undefined : currentFilter;
      const data = await hitlApi.listHitlItems(statusParam);
      setItems(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to load HITL queue.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadItems(filter);
  }, [filter, loadItems]);

  async function handleClaim(item: HitlItem) {
    setPendingActionId(item.id);
    setError(null);
    try {
      const updated = await hitlApi.claimHitlItem(item.id);
      setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to claim item.");
    } finally {
      setPendingActionId(null);
    }
  }

  async function handleResolve(item: HitlItem, notes: string, dismiss: boolean) {
    setPendingActionId(item.id);
    setError(null);
    try {
      const updated = await hitlApi.resolveHitlItem(item.id, {
        resolution_notes: notes,
        dismiss,
      });
      // A resolved/dismissed item no longer belongs in the "actionable"
      // filter view -- remove it locally rather than waiting on a refetch,
      // so the queue visibly shrinks as items get worked, same feedback
      // an admin would expect from a real review queue.
      if (filter === "actionable") {
        setItems((prev) => prev.filter((i) => i.id !== updated.id));
      } else {
        setItems((prev) => prev.map((i) => (i.id === updated.id ? updated : i)));
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to resolve item.");
    } finally {
      setPendingActionId(null);
    }
  }

  return (
    <AppShell>
      <div className={styles.header}>
        <h1>HITL Review Queue</h1>
        <div className={styles.filterGroup}>
          {(["actionable", "pending", "in_review", "resolved", "dismissed"] as FilterOption[]).map(
            (opt) => (
              <button
                key={opt}
                className={
                  filter === opt
                    ? `${styles.filterButton} ${styles.filterButtonActive}`
                    : styles.filterButton
                }
                onClick={() => setFilter(opt)}
              >
                {opt === "actionable" ? "Pending review" : opt.replace("_", " ")}
              </button>
            )
          )}
        </div>
      </div>

      {error && <div className={styles.errorBanner}>{error}</div>}

      {isLoading ? (
        <div className={styles.loadingState}>Loading queue...</div>
      ) : items.length === 0 ? (
        <div className={styles.emptyState}>
          <div className={styles.emptyStateTitle}>Nothing here right now</div>
          <p>
            {filter === "actionable"
              ? "No items currently need review. This queue will populate once the transcript quality engine and NER validation pipeline (Phases 10\u201312) start flagging items automatically."
              : `No ${filter.replace("_", " ")} items.`}
          </p>
        </div>
      ) : (
        <div className={styles.list}>
          {items.map((item) => (
            <HitlItemCard
              key={item.id}
              item={item}
              isPending={pendingActionId === item.id}
              onClaim={() => handleClaim(item)}
              onResolve={(notes, dismiss) => handleResolve(item, notes, dismiss)}
            />
          ))}
        </div>
      )}
    </AppShell>
  );
}

interface HitlItemCardProps {
  item: HitlItem;
  isPending: boolean;
  onClaim: () => void;
  onResolve: (notes: string, dismiss: boolean) => void;
}

function HitlItemCard({ item, isPending, onClaim, onResolve }: HitlItemCardProps) {
  const [showResolveForm, setShowResolveForm] = useState(false);
  const [notes, setNotes] = useState("");

  function submitResolve(dismiss: boolean) {
    if (!notes.trim()) return;
    onResolve(notes, dismiss);
    setNotes("");
    setShowResolveForm(false);
  }

  return (
    <div className={styles.itemCard}>
      <div className={styles.itemHeader}>
        <div>
          <span className={styles.reasonBadge}>{HITL_REASON_LABELS[item.reason]}</span>
          <p className={styles.message}>{item.user_facing_message}</p>
          <div className={styles.meta}>
            Flagged {formatDateTime(item.created_at)}
            {item.resolved_at && ` · Resolved ${formatDateTime(item.resolved_at)}`}
          </div>
        </div>
        <span className={`${styles.statusBadge} ${STATUS_CLASS[item.status]}`}>
          {item.status.replace("_", " ")}
        </span>
      </div>

      {item.status === "pending" && (
        <div className={styles.actions}>
          <button className={styles.actionButton} disabled={isPending} onClick={onClaim}>
            {isPending ? "Claiming..." : "Claim for review"}
          </button>
        </div>
      )}

      {item.status === "in_review" && !showResolveForm && (
        <div className={styles.actions}>
          <button
            className={styles.actionButton}
            disabled={isPending}
            onClick={() => setShowResolveForm(true)}
          >
            Resolve
          </button>
        </div>
      )}

      {item.status === "in_review" && showResolveForm && (
        <div className={styles.resolveForm}>
          <textarea
            className={styles.textarea}
            placeholder="Resolution notes (required) — what did you find, what action was taken..."
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <div className={styles.actions}>
            <button
              className={styles.actionButton}
              disabled={isPending || !notes.trim()}
              onClick={() => submitResolve(false)}
            >
              Mark resolved
            </button>
            <button
              className={styles.secondaryButton}
              disabled={isPending || !notes.trim()}
              onClick={() => submitResolve(true)}
            >
              Dismiss (false positive)
            </button>
            <button
              className={styles.secondaryButton}
              disabled={isPending}
              onClick={() => setShowResolveForm(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {(item.status === "resolved" || item.status === "dismissed") && item.resolution_notes && (
        <div className={styles.resolveForm} style={{ fontSize: "0.85rem", color: "var(--color-text-secondary)" }}>
          <strong>Resolution notes:</strong> {item.resolution_notes}
        </div>
      )}
    </div>
  );
}