import { useState, useEffect, useCallback } from "react";
import { AppShell } from "../components/AppShell";
import * as auditApi from "../api/auditLogs";
import type { AuditLogEntry, AuditAction } from "../types/audit";
import { ApiError } from "../api/client";
import styles from "./AuditLogPage.module.css";

const PAGE_SIZE = 50;

const ACTION_OPTIONS: AuditAction[] = [
  "login_success",
  "login_failed",
  "logout",
  "create",
  "read",
  "update",
  "delete",
  "soft_delete",
  "approve",
  "reject",
  "edit_ai_output",
  "export_pdf",
  "hitl_resolve",
];

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

interface Filters {
  action: string;
  target_entity_type: string;
  success: string; // "" | "true" | "false"
}

const EMPTY_FILTERS: Filters = { action: "", target_entity_type: "", success: "" };

export function AuditLogPage() {
  const [entries, setEntries] = useState<AuditLogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [offset, setOffset] = useState(0);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const loadEntries = useCallback(async (currentFilters: Filters, currentOffset: number) => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await auditApi.listAuditLogs({
        action: currentFilters.action ? (currentFilters.action as AuditAction) : undefined,
        target_entity_type: currentFilters.target_entity_type || undefined,
        success:
          currentFilters.success === "" ? undefined : currentFilters.success === "true",
        limit: PAGE_SIZE,
        offset: currentOffset,
      });
      setEntries(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Failed to load audit logs.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadEntries(filters, offset);
  }, [filters, offset, loadEntries]);

  function updateFilter<K extends keyof Filters>(key: K, value: Filters[K]) {
    setOffset(0); // any filter change resets to the first page
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  function clearFilters() {
    setOffset(0);
    setFilters(EMPTY_FILTERS);
  }

  const hasActiveFilters =
    filters.action !== "" || filters.target_entity_type !== "" || filters.success !== "";

  return (
    <AppShell>
      <div className={styles.header}>
        <h1>Audit Log</h1>
      </div>

      <div className={styles.filterBar}>
        <div className={styles.filterField}>
          <label className={styles.filterLabel} htmlFor="action-filter">
            Action
          </label>
          <select
            id="action-filter"
            className={styles.select}
            value={filters.action}
            onChange={(e) => updateFilter("action", e.target.value)}
          >
            <option value="">All actions</option>
            {ACTION_OPTIONS.map((a) => (
              <option key={a} value={a}>
                {a.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </div>

        <div className={styles.filterField}>
          <label className={styles.filterLabel} htmlFor="entity-filter">
            Entity type
          </label>
          <input
            id="entity-filter"
            className={styles.input}
            placeholder="e.g. patient, user"
            value={filters.target_entity_type}
            onChange={(e) => updateFilter("target_entity_type", e.target.value)}
          />
        </div>

        <div className={styles.filterField}>
          <label className={styles.filterLabel} htmlFor="success-filter">
            Result
          </label>
          <select
            id="success-filter"
            className={styles.select}
            value={filters.success}
            onChange={(e) => updateFilter("success", e.target.value)}
          >
            <option value="">All</option>
            <option value="true">Success only</option>
            <option value="false">Failures only</option>
          </select>
        </div>

        {hasActiveFilters && (
          <button className={styles.clearButton} onClick={clearFilters}>
            Clear filters
          </button>
        )}
      </div>

      {error && <div className={styles.errorBanner}>{error}</div>}

      <div className={styles.card}>
        {isLoading ? (
          <div className={styles.loadingState}>Loading audit log...</div>
        ) : entries.length === 0 ? (
          <div className={styles.emptyState}>
            {hasActiveFilters
              ? "No audit log entries match these filters."
              : "No audit log entries yet."}
          </div>
        ) : (
          <>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Action</th>
                  <th>Actor role</th>
                  <th>Target</th>
                  <th>Result</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <>
                    <tr key={entry.id}>
                      <td className={styles.timestamp}>{formatDateTime(entry.occurred_at)}</td>
                      <td>
                        <span className={styles.actionBadge + " " + (entry.success ? styles.actionSuccess : styles.actionFailed)}>
                          {entry.action.replace(/_/g, " ")}
                        </span>
                      </td>
                      <td>{entry.actor_role ?? "—"}</td>
                      <td className={styles.entityCell}>
                        {entry.target_entity_type ?? "—"}
                        {entry.target_entity_id && (
                          <div>{entry.target_entity_id.slice(0, 8)}…</div>
                        )}
                      </td>
                      <td>
                        {entry.success ? (
                          <span className={styles.successIcon}>✓ Success</span>
                        ) : (
                          <span className={styles.failIcon}>✕ Failed</span>
                        )}
                      </td>
                      <td>
                        {entry.metadata_json && (
                          <button
                            className={styles.metaToggle}
                            onClick={() =>
                              setExpandedId(expandedId === entry.id ? null : entry.id)
                            }
                          >
                            {expandedId === entry.id ? "Hide" : "View"}
                          </button>
                        )}
                      </td>
                    </tr>
                    {expandedId === entry.id && entry.metadata_json && (
                      <tr key={`${entry.id}-meta`}>
                        <td colSpan={6}>
                          <pre className={styles.metaJson}>
                            {JSON.stringify(entry.metadata_json, null, 2)}
                          </pre>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>

            <div className={styles.pagination}>
              <span className={styles.pageInfo}>
                Showing {offset + 1}–{offset + entries.length}
                {entries.length === PAGE_SIZE ? "+" : ""}
              </span>
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <button
                  className={styles.pageButton}
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                >
                  Previous
                </button>
                <button
                  className={styles.pageButton}
                  disabled={entries.length < PAGE_SIZE}
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}