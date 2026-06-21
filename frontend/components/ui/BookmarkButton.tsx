"use client";

import { useState, useEffect } from "react";
import { Bookmark, BookmarkCheck } from "lucide-react";
import { BASE } from "@/lib/api";

interface Props {
  entityType: "opportunity" | "paper" | "concept" | "domain";
  entityId: string;
  entityTitle?: string;
  size?: number;
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
  };
  return fetch(`${BASE}${path}`, { ...opts, headers });
}

export function BookmarkButton({ entityType, entityId, entityTitle, size = 15 }: Props) {
  const [bookmarked,   setBookmarked]   = useState(false);
  const [bookmarkId,   setBookmarkId]   = useState<string | null>(null);
  const [loading,      setLoading]      = useState(false);
  const [checked,      setChecked]      = useState(false);   // have we fetched status yet?

  useEffect(() => {
    if (!getToken()) { setChecked(true); return; }
    apiFetch(`/bookmarks/check/${entityType}/${encodeURIComponent(entityId)}`)
      .then(r => r.json())
      .then(d => {
        setBookmarked(d.bookmarked ?? false);
        setBookmarkId(d.bookmark_id ?? null);
      })
      .catch(() => {})
      .finally(() => setChecked(true));
  }, [entityType, entityId]);

  const toggle = async () => {
    if (!getToken()) {
      alert("Sign in to bookmark items.");
      return;
    }
    setLoading(true);
    try {
      if (bookmarked && bookmarkId) {
        const res = await apiFetch(`/bookmarks/${bookmarkId}`, { method: "DELETE" });
        if (res.ok || res.status === 204) {
          setBookmarked(false);
          setBookmarkId(null);
        }
      } else {
        const res = await apiFetch("/bookmarks", {
          method: "POST",
          body: JSON.stringify({ entity_type: entityType, entity_id: entityId, entity_title: entityTitle }),
        });
        if (res.ok || res.status === 201) {
          const d = await res.json();
          setBookmarked(true);
          setBookmarkId(d.id);
        }
      }
    } finally {
      setLoading(false);
    }
  };

  if (!checked) return null;   // don't flash the wrong state

  return (
    <button
      onClick={toggle}
      disabled={loading}
      title={bookmarked ? "Remove bookmark" : "Bookmark this"}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "5px",
        padding: "5px 10px",
        border: "1px solid",
        borderColor: bookmarked ? "var(--color-indigo)" : "var(--color-border)",
        background: bookmarked ? "rgba(99,102,241,0.1)" : "transparent",
        color: bookmarked ? "var(--color-indigo)" : "var(--color-text-muted)",
        borderRadius: "4px",
        cursor: loading ? "wait" : "pointer",
        fontSize: "12px",
        fontFamily: "var(--font-sans)",
        transition: "all 0.15s",
      }}
    >
      {bookmarked
        ? <BookmarkCheck size={size} />
        : <Bookmark size={size} />
      }
      {bookmarked ? "Saved" : "Save"}
    </button>
  );
}
