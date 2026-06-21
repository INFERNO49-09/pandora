"use client";

import { useEffect, useState } from "react";
import { SectionHeader, Badge, EmptyState, Skeleton } from "@/components/ui/primitives";
import { AlertTriangle, RefreshCw, ChevronDown, ChevronUp } from "lucide-react";
import { api, Contradiction } from "@/lib/api";

const TYPE_META: Record<string, { label: string; color: string; bg: string }> = {
  quantitative:   { label: "Quantitative",   color: "var(--color-amber)",  bg: "rgba(245,158,11,0.10)" },
  qualitative:    { label: "Qualitative",    color: "var(--color-indigo)", bg: "rgba(99,102,241,0.10)" },
  methodological: { label: "Methodological", color: "var(--color-red)",    bg: "rgba(239,68,68,0.10)"  },
};

export default function ContradictionsPage() {
  const [contradictions, setContradictions] = useState<Contradiction[]>([]);
  const [loading,   setLoading]   = useState(true);
  const [scanning,  setScanning]  = useState(false);
  const [domain,    setDomain]    = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [expanded,  setExpanded]  = useState<Record<string, boolean>>({});

  const fetchContradictions = async (d?: string, t?: string) => {
    setLoading(true);
    try {
      const data = await api.contradictions.list({
        domain: d || undefined,
        contradiction_type: t || undefined,
        min_confidence: 0.65,
        limit: 50,
      });
      setContradictions(data.contradictions || []);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const triggerScan = async () => {
    setScanning(true);
    try {
      await api.contradictions.scan(domain || undefined);
      await new Promise(r => setTimeout(r, 3000));
      await fetchContradictions(domain, typeFilter);
    } catch (e) {
      console.error(e);
    } finally {
      setScanning(false);
    }
  };

  useEffect(() => { fetchContradictions(); }, []);

  const toggle = (id: string) => setExpanded(p => ({ ...p, [id]: !p[id] }));

  return (
    <div style={{ padding: "32px", maxWidth: "1000px" }}>

      {/* Header */}
      <div style={{ marginBottom: "28px" }}>
        <p style={{ color: "var(--color-indigo)", fontFamily: "var(--font-mono)", fontSize: "11px", letterSpacing: "0.1em", textTransform: "uppercase", margin: "0 0 8px" }}>
          PANDORA / CONTRADICTIONS
        </p>
        <h1 style={{ fontSize: "22px", fontWeight: 600, margin: "0 0 4px" }}>Contradiction Detector</h1>
        <p style={{ color: "var(--color-text-secondary)", margin: 0, fontSize: "13px" }}>
          Scientific disagreements detected across the knowledge graph
        </p>
      </div>

      {/* Controls */}
      <div style={{ display: "flex", gap: "8px", marginBottom: "20px", flexWrap: "wrap", alignItems: "center" }}>
        <input
          value={domain}
          onChange={e => setDomain(e.target.value)}
          placeholder="Filter by domain..."
          style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", color: "var(--color-text-primary)", padding: "6px 12px", fontSize: "12px", fontFamily: "var(--font-mono)", outline: "none", width: "180px" }}
        />

        {["", "quantitative", "qualitative", "methodological"].map(t => (
          <button
            key={t || "all"}
            onClick={() => { setTypeFilter(t); fetchContradictions(domain, t); }}
            style={{
              padding: "5px 12px", fontSize: "11px", fontFamily: "var(--font-mono)",
              cursor: "pointer", border: "1px solid",
              borderColor: typeFilter === t ? "var(--color-indigo)" : "var(--color-border)",
              color:       typeFilter === t ? "var(--color-indigo)" : "var(--color-text-muted)",
              background:  typeFilter === t ? "rgba(99,102,241,0.08)" : "transparent",
            }}
          >
            {t || "ALL"}
          </button>
        ))}

        <button
          onClick={() => fetchContradictions(domain, typeFilter)}
          style={{ marginLeft: "auto", padding: "5px 12px", fontSize: "11px", fontFamily: "var(--font-mono)", cursor: "pointer", border: "1px solid var(--color-border)", color: "var(--color-text-muted)", background: "transparent", display: "flex", alignItems: "center", gap: "4px" }}
        >
          <RefreshCw size={11} /> REFRESH
        </button>

        <button
          onClick={triggerScan}
          disabled={scanning}
          style={{ padding: "5px 14px", fontSize: "11px", fontFamily: "var(--font-mono)", cursor: "pointer", border: "none", color: "white", background: scanning ? "var(--color-indigo-dim)" : "var(--color-indigo)", opacity: scanning ? 0.7 : 1 }}
        >
          {scanning ? "SCANNING..." : "RUN SCAN"}
        </button>
      </div>

      {/* Contradiction count */}
      {!loading && (
        <div style={{ display: "flex", gap: "16px", marginBottom: "16px" }}>
          {(["quantitative", "qualitative", "methodological"] as const).map(t => {
            const count = contradictions.filter(c => c.contradiction_type === t).length;
            const meta = TYPE_META[t];
            return (
              <div key={t} style={{ padding: "8px 14px", background: meta.bg, border: `1px solid ${meta.color}40`, display: "flex", gap: "8px", alignItems: "center" }}>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "18px", fontWeight: 500, color: meta.color }}>{count}</span>
                <span style={{ fontSize: "11px", color: meta.color, textTransform: "uppercase", letterSpacing: "0.06em" }}>{meta.label}</span>
              </div>
            );
          })}
        </div>
      )}

      {/* List */}
      {loading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          {[...Array(5)].map((_, i) => <Skeleton key={i} height={80} />)}
        </div>
      ) : contradictions.length === 0 ? (
        <EmptyState
          icon={<AlertTriangle size={32} />}
          title="No contradictions detected"
          description="Run a scan to detect scientific disagreements. Requires papers with shared datasets and metrics."
          action={
            <button onClick={triggerScan} style={{ marginTop: "8px", padding: "8px 16px", background: "var(--color-indigo)", border: "none", color: "white", fontSize: "12px", fontFamily: "var(--font-mono)", cursor: "pointer" }}>
              RUN SCAN
            </button>
          }
        />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "1px", background: "var(--color-border)", border: "1px solid var(--color-border)" }}>
          {contradictions.map((c, i) => {
            const key  = c.id || `${i}`;
            const meta = TYPE_META[c.contradiction_type] ?? TYPE_META.qualitative;
            const open = expanded[key];

            return (
              <div key={key} style={{ background: "var(--color-surface)" }}>
                {/* Header row */}
                <button
                  onClick={() => toggle(key)}
                  style={{ width: "100%", background: "none", border: "none", padding: "14px 16px", textAlign: "left", cursor: "pointer", display: "grid", gridTemplateColumns: "auto 1fr auto auto", gap: "12px", alignItems: "center" }}
                >
                  {/* Confidence */}
                  <div style={{ textAlign: "center", minWidth: "40px" }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "16px", fontWeight: 500, color: meta.color }}>
                      {Math.round(c.confidence_score * 100)}
                    </span>
                    <p style={{ margin: 0, fontSize: "9px", color: "var(--color-text-muted)", textTransform: "uppercase" }}>conf</p>
                  </div>

                  {/* Title */}
                  <div>
                    <p style={{ margin: 0, fontSize: "13px", fontWeight: 500, color: "var(--color-text-primary)", lineHeight: 1.3 }}>
                      {c.paper_a_title?.slice(0, 70) || "Unknown paper"}…
                      <span style={{ color: "var(--color-text-muted)", margin: "0 6px" }}>vs</span>
                      {c.paper_b_title?.slice(0, 70) || "Unknown paper"}…
                    </p>
                    <p style={{ margin: "4px 0 0", fontSize: "11px", color: "var(--color-text-muted)" }}>
                      {c.explanation?.slice(0, 120)}
                    </p>
                  </div>

                  {/* Type badge */}
                  <span style={{ padding: "2px 8px", fontSize: "10px", fontFamily: "var(--font-mono)", background: meta.bg, color: meta.color, border: `1px solid ${meta.color}40`, whiteSpace: "nowrap" }}>
                    {meta.label.toUpperCase()}
                  </span>

                  {/* Expand chevron */}
                  <span style={{ color: "var(--color-text-muted)" }}>
                    {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                  </span>
                </button>

                {/* Expanded detail */}
                {open && (
                  <div style={{ padding: "0 16px 16px", borderTop: "1px solid var(--color-border)", marginTop: "-1px" }}>
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px", marginTop: "12px" }}>

                      {/* Quantitative comparison */}
                      {c.paper_a_value != null && c.paper_b_value != null && (
                        <div style={{ gridColumn: "1 / -1", background: "var(--color-surface-2)", border: "1px solid var(--color-border)", padding: "12px", display: "grid", gridTemplateColumns: "1fr auto 1fr", gap: "12px", alignItems: "center" }}>
                          <div style={{ textAlign: "center" }}>
                            <p style={{ margin: 0, fontSize: "10px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Paper A</p>
                            <p style={{ margin: "4px 0 0", fontFamily: "var(--font-mono)", fontSize: "22px", color: "var(--color-indigo)", fontWeight: 500 }}>{c.paper_a_value?.toFixed(2)}</p>
                          </div>
                          <div style={{ textAlign: "center" }}>
                            <p style={{ margin: 0, fontSize: "11px", color: "var(--color-text-muted)" }}>{c.metric ?? "metric"}</p>
                            <p style={{ margin: "2px 0 0", fontSize: "10px", color: "var(--color-text-muted)" }}>{c.dataset ?? "dataset"}</p>
                          </div>
                          <div style={{ textAlign: "center" }}>
                            <p style={{ margin: 0, fontSize: "10px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Paper B</p>
                            <p style={{ margin: "4px 0 0", fontFamily: "var(--font-mono)", fontSize: "22px", color: "var(--color-amber)", fontWeight: 500 }}>{c.paper_b_value?.toFixed(2)}</p>
                          </div>
                        </div>
                      )}

                      {/* Papers */}
                      {[{ title: c.paper_a_title, id: c.paper_a_id, label: "Paper A" }, { title: c.paper_b_title, id: c.paper_b_id, label: "Paper B" }].map(({ title, id, label }) => (
                        <div key={label} style={{ background: "var(--color-surface-2)", border: "1px solid var(--color-border)", padding: "10px" }}>
                          <p style={{ margin: "0 0 4px", fontSize: "10px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</p>
                          <p style={{ margin: 0, fontSize: "12px", color: "var(--color-text-primary)", lineHeight: 1.4 }}>{title}</p>
                          <p style={{ margin: "4px 0 0", fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--color-text-muted)" }}>{id}</p>
                        </div>
                      ))}

                      {/* Explanation */}
                      <div style={{ gridColumn: "1 / -1" }}>
                        <p style={{ margin: "0 0 4px", fontSize: "10px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Analysis</p>
                        <p style={{ margin: 0, fontSize: "13px", color: "var(--color-text-secondary)", lineHeight: 1.6 }}>{c.explanation}</p>
                        {c.methodology_analysis && (
                          <p style={{ margin: "6px 0 0", fontSize: "12px", color: "var(--color-text-muted)", fontStyle: "italic" }}>Topic: {c.methodology_analysis}</p>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
