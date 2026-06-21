"use client";

import { useState, useEffect, useCallback } from "react";
import { Badge, EmptyState, SectionHeader } from "@/components/ui/primitives";
import { Bookmark, BookmarkX, ExternalLink, Pencil, Check, X } from "lucide-react";
import Link from "next/link";
import { scoreColor } from "@/lib/utils";
import { BASE } from "@/lib/api";

interface BookmarkItem {
  id: string;
  entity_type: "opportunity" | "paper" | "concept" | "domain";
  entity_id: string;
  entity_title: string | null;
  notes: string | null;
  created_at: string;
}

const ENTITY_HREF: Record<string, (id: string) => string> = {
  opportunity: (id) => `/discover/${id}`,
  paper:       (id) => `/graph/node/${id}`,
  concept:     (id) => `/graph/node/${id}`,
  domain:      (id) => `/map?focus=${id}`,
};

const ENTITY_COLORS: Record<string, string> = {
  opportunity: "indigo",
  paper:       "amber",
  concept:     "green",
  domain:      "muted",
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const h = Math.floor(diff / 3_600_000);
  if (h < 1)   return "just now";
  if (h < 24)  return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30)  return `${d}d ago`;
  return `${Math.floor(d / 30)}mo ago`;
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("pandora_token");
}

async function apiFetch(path: string, opts: RequestInit = {}) {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(opts.headers as Record<string, string> ?? {}),
  };
  return fetch(`${BASE}${path}`, { ...opts, headers });
}

export default function BookmarksPage() {
  const [bookmarks,    setBookmarks]    = useState<BookmarkItem[]>([]);
  const [loading,      setLoading]      = useState(true);
  const [filter,       setFilter]       = useState<string>("all");
  const [editingId,    setEditingId]    = useState<string | null>(null);
  const [editNote,     setEditNote]     = useState("");
  const [savingNote,   setSavingNote]   = useState(false);
  const [error,        setError]        = useState<string | null>(null);

  const fetchBookmarks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = filter !== "all" ? `?entity_type=${filter}&limit=100` : "?limit=100";
      const res = await apiFetch(`/bookmarks${params}`);
      if (res.status === 401) { setError("Sign in to view bookmarks."); return; }
      if (!res.ok) throw new Error("Failed to load bookmarks");
      const data = await res.json();
      setBookmarks(data.bookmarks ?? []);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => { fetchBookmarks(); }, [fetchBookmarks]);

  const removeBookmark = async (bm: BookmarkItem) => {
    const res = await apiFetch(`/bookmarks/${bm.id}`, { method: "DELETE" });
    if (res.ok || res.status === 204) {
      setBookmarks(prev => prev.filter(b => b.id !== bm.id));
    }
  };

  const startEdit = (bm: BookmarkItem) => {
    setEditingId(bm.id);
    setEditNote(bm.notes ?? "");
  };

  const cancelEdit = () => { setEditingId(null); setEditNote(""); };

  const saveNote = async (bm: BookmarkItem) => {
    setSavingNote(true);
    const res = await apiFetch(`/bookmarks/${bm.id}`, {
      method: "PATCH",
      body: JSON.stringify({ notes: editNote }),
    });
    if (res.ok) {
      const updated = await res.json();
      setBookmarks(prev => prev.map(b => b.id === bm.id ? { ...b, notes: updated.notes } : b));
    }
    setSavingNote(false);
    setEditingId(null);
  };

  const FILTERS = ["all", "opportunity", "paper", "concept", "domain"];

  const filtered = filter === "all" ? bookmarks : bookmarks.filter(b => b.entity_type === filter);

  return (
    <div style={{ padding: "32px", maxWidth: "900px" }}>
      {/* Header */}
      <div style={{ marginBottom: "28px" }}>
        <p style={{
          color: "var(--color-indigo)", fontFamily: "var(--font-mono)",
          fontSize: "11px", letterSpacing: "0.1em", textTransform: "uppercase",
          margin: "0 0 8px",
        }}>
          PANDORA / BOOKMARKS
        </p>
        <h1 style={{ fontSize: "22px", fontWeight: 600, margin: "0 0 4px", color: "var(--color-text-primary)" }}>
          Saved Items
        </h1>
        <p style={{ color: "var(--color-text-secondary)", margin: 0, fontSize: "13px" }}>
          {bookmarks.length} item{bookmarks.length !== 1 ? "s" : ""} saved across all types
        </p>
      </div>

      {/* Filter bar */}
      <div style={{ display: "flex", gap: "4px", marginBottom: "20px" }}>
        {FILTERS.map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={{
              padding: "5px 12px",
              borderRadius: "4px",
              border: "1px solid",
              borderColor: filter === f ? "var(--color-indigo)" : "var(--color-border)",
              background: filter === f ? "rgba(99,102,241,0.12)" : "var(--color-surface)",
              color: filter === f ? "var(--color-indigo)" : "var(--color-text-muted)",
              fontSize: "12px",
              cursor: "pointer",
              fontFamily: "var(--font-mono)",
              textTransform: "capitalize",
            }}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Content */}
      {error ? (
        <div style={{
          padding: "24px", background: "var(--color-surface)",
          border: "1px solid var(--color-border)", color: "var(--color-text-muted)",
          fontSize: "13px", textAlign: "center",
        }}>
          {error}
        </div>
      ) : loading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "1px" }}>
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} style={{
              height: "72px", background: "var(--color-surface)",
              border: "1px solid var(--color-border)", animation: "pulse 1.5s infinite",
            }} />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={<Bookmark size={32} />}
          title="No bookmarks yet"
          description={
            filter === "all"
              ? "Save opportunities, papers, and concepts as you explore the graph."
              : `No ${filter} bookmarks found.`
          }
        />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "1px", background: "var(--color-border)", border: "1px solid var(--color-border)" }}>
          {filtered.map(bm => {
            const href = ENTITY_HREF[bm.entity_type]?.(bm.entity_id);
            const isEditing = editingId === bm.id;
            return (
              <div
                key={bm.id}
                style={{
                  background: "var(--color-surface)",
                  padding: "14px 16px",
                  display: "flex",
                  flexDirection: "column",
                  gap: "8px",
                }}
              >
                {/* Top row */}
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "12px" }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                      <Badge variant={ENTITY_COLORS[bm.entity_type] as "indigo" | "amber" | "green" | "muted"}>
                        {bm.entity_type}
                      </Badge>
                      <span style={{
                        fontSize: "13px", fontWeight: 500,
                        color: "var(--color-text-primary)",
                        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                      }}>
                        {bm.entity_title ?? bm.entity_id}
                      </span>
                    </div>
                    <p style={{ margin: "3px 0 0", fontSize: "11px", color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
                      {timeAgo(bm.created_at)}
                    </p>
                  </div>

                  {/* Actions */}
                  <div style={{ display: "flex", gap: "6px", flexShrink: 0 }}>
                    {href && (
                      <Link href={href} title="Open">
                        <button style={actionBtn}>
                          <ExternalLink size={13} />
                        </button>
                      </Link>
                    )}
                    <button title="Edit notes" onClick={() => startEdit(bm)} style={actionBtn}>
                      <Pencil size={13} />
                    </button>
                    <button title="Remove" onClick={() => removeBookmark(bm)} style={{ ...actionBtn, color: "var(--color-red, #ef4444)" }}>
                      <BookmarkX size={13} />
                    </button>
                  </div>
                </div>

                {/* Notes row */}
                {isEditing ? (
                  <div style={{ display: "flex", gap: "6px", alignItems: "flex-end" }}>
                    <textarea
                      value={editNote}
                      onChange={e => setEditNote(e.target.value)}
                      rows={2}
                      placeholder="Add a note..."
                      style={{
                        flex: 1, resize: "vertical", padding: "6px 8px",
                        background: "var(--color-bg)", border: "1px solid var(--color-border)",
                        color: "var(--color-text-primary)", fontSize: "12px",
                        fontFamily: "var(--font-sans)", borderRadius: "4px",
                      }}
                    />
                    <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                      <button onClick={() => saveNote(bm)} disabled={savingNote} style={{ ...actionBtn, color: "var(--color-indigo)" }}>
                        <Check size={13} />
                      </button>
                      <button onClick={cancelEdit} style={actionBtn}>
                        <X size={13} />
                      </button>
                    </div>
                  </div>
                ) : bm.notes ? (
                  <p style={{
                    margin: 0, fontSize: "12px", color: "var(--color-text-secondary)",
                    borderLeft: "2px solid var(--color-border)", paddingLeft: "8px",
                    lineHeight: 1.5,
                  }}>
                    {bm.notes}
                  </p>
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

const actionBtn: React.CSSProperties = {
  width: "28px", height: "28px",
  display: "flex", alignItems: "center", justifyContent: "center",
  border: "1px solid var(--color-border)",
  background: "transparent",
  color: "var(--color-text-muted)",
  borderRadius: "4px",
  cursor: "pointer",
};
