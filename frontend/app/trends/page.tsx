"use client";

import { useEffect, useState } from "react";
import { api, type TrendConcept, type TrendDomain, type EmergingIntersection } from "@/lib/api";
import { SectionHeader, Badge, Skeleton } from "@/components/ui/primitives";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, LineChart, Line, CartesianGrid } from "recharts";
import { TrendingUp } from "lucide-react";

export default function TrendsPage() {
  const [concepts,  setConcepts]  = useState<TrendConcept[]>([]);
  const [domains,   setDomains]   = useState<TrendDomain[]>([]);
  const [emerging,  setEmerging]  = useState<EmergingIntersection[]>([]);
  const [timeline,  setTimeline]  = useState<{ year: number; papers: number }[]>([]);
  const [selected,  setSelected]  = useState<string>("");
  const [loading,   setLoading]   = useState(true);

  useEffect(() => {
    Promise.all([
      api.trends.concepts(20),
      api.trends.domains(20),
      api.trends.emerging(10),
    ]).then(([c, d, e]) => {
      setConcepts(c.trends);
      setDomains(d.domains);
      setEmerging(e.emerging_intersections);
      if (d.domains[0]) setSelected(d.domains[0].name);
    }).catch(console.error).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selected) return;
    api.trends.timeline(selected, 10).then((r) => setTimeline(r.timeline)).catch(console.error);
  }, [selected]);

  return (
    <div style={{ padding: "32px", maxWidth: "1100px" }}>

      <div style={{ marginBottom: "28px" }}>
        <p style={{ color: "var(--color-indigo)", fontFamily: "var(--font-mono)", fontSize: "11px", letterSpacing: "0.1em", textTransform: "uppercase", margin: "0 0 8px" }}>
          PANDORA / TRENDS
        </p>
        <h1 style={{ fontSize: "22px", fontWeight: 600, margin: "0 0 4px" }}>Trend Analysis</h1>
        <p style={{ color: "var(--color-text-secondary)", margin: 0, fontSize: "13px" }}>
          Fastest-growing concepts and domains in the knowledge graph
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px", marginBottom: "24px" }}>

        {/* Domain growth */}
        <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", padding: "18px" }}>
          <SectionHeader title="Domain Growth" sub="Recent papers / total papers ratio" />
          {loading ? (
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {[...Array(6)].map((_, i) => <Skeleton key={i} height={24} />)}
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              {domains.slice(0, 12).map((d) => (
                <button
                  key={d.id}
                  onClick={() => setSelected(d.name)}
                  style={{
                    background: selected === d.name ? "rgba(99,102,241,0.08)" : "none",
                    border: "1px solid",
                    borderColor: selected === d.name ? "var(--color-indigo)" : "transparent",
                    padding: "6px 8px",
                    textAlign: "left",
                    cursor: "pointer",
                    display: "grid",
                    gridTemplateColumns: "1fr 60px 40px",
                    gap: "8px",
                    alignItems: "center",
                  }}
                >
                  <span style={{ fontSize: "12px", color: selected === d.name ? "var(--color-text-primary)" : "var(--color-text-secondary)", fontWeight: selected === d.name ? 500 : 400 }}>
                    {d.name}
                  </span>
                  <div style={{ height: "3px", background: "var(--color-border-2)", position: "relative", overflow: "hidden" }}>
                    <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${Math.min(100, d.growth_ratio * 200)}%`, background: "var(--color-indigo)" }} />
                  </div>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--color-text-muted)", textAlign: "right" }}>
                    {(d.growth_ratio * 100).toFixed(0)}%
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Timeline chart */}
        <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", padding: "18px" }}>
          <SectionHeader
            title={selected ? `${selected} — Publication Timeline` : "Timeline"}
            sub="Papers per year"
          />
          {timeline.length > 0 ? (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={timeline} margin={{ top: 4, right: 4, bottom: 4, left: -16 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="year" tick={{ fontSize: 10, fill: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }} />
                <YAxis tick={{ fontSize: 10, fill: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }} />
                <Tooltip
                  contentStyle={{ background: "var(--color-surface-2)", border: "1px solid var(--color-border)", fontSize: "12px", fontFamily: "var(--font-mono)" }}
                  labelStyle={{ color: "var(--color-text-primary)" }}
                  itemStyle={{ color: "var(--color-indigo)" }}
                />
                <Line type="monotone" dataKey="papers" stroke="var(--color-indigo)" strokeWidth={2} dot={false} activeDot={{ r: 4, fill: "var(--color-indigo)" }} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ height: "240px", display: "flex", alignItems: "center", justifyContent: "center" }}>
              <p style={{ color: "var(--color-text-muted)", fontSize: "13px" }}>
                {loading ? "Loading..." : "Select a domain to view timeline"}
              </p>
            </div>
          )}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px" }}>

        {/* Top concepts */}
        <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", padding: "18px" }}>
          <SectionHeader title="Emerging Concepts" sub="Highest recency ratio" />
          {loading ? (
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {[...Array(8)].map((_, i) => <Skeleton key={i} height={20} />)}
            </div>
          ) : (
            <ResponsiveContainer width="100%" height={280}>
              <BarChart
                data={concepts.slice(0, 10).map((c) => ({ name: c.name.length > 22 ? c.name.slice(0, 22) + "…" : c.name, ratio: Math.round(c.recency_ratio * 100) }))}
                layout="vertical"
                margin={{ top: 0, right: 40, bottom: 0, left: 0 }}
              >
                <XAxis type="number" tick={{ fontSize: 10, fill: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }} domain={[0, 100]} unit="%" />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 10, fill: "var(--color-text-secondary)" }} width={140} />
                <Tooltip
                  contentStyle={{ background: "var(--color-surface-2)", border: "1px solid var(--color-border)", fontSize: "12px", fontFamily: "var(--font-mono)" }}
                  itemStyle={{ color: "var(--color-indigo)" }}
                  formatter={(v: any) => [`${v}%`, "Recency ratio"]}
                />
                <Bar dataKey="ratio" fill="var(--color-indigo)" radius={[0, 2, 2, 0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* Emerging intersections */}
        <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", padding: "18px" }}>
          <SectionHeader title="Emerging Intersections" sub="Domain pairs forming new bridges" />
          {loading ? (
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {[...Array(6)].map((_, i) => <Skeleton key={i} height={40} />)}
            </div>
          ) : emerging.length === 0 ? (
            <p style={{ color: "var(--color-text-muted)", fontSize: "13px" }}>No emerging intersections detected yet.</p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              {emerging.map((e, i) => (
                <div
                  key={i}
                  style={{
                    padding: "10px 12px",
                    background: "var(--color-surface-2)",
                    border: "1px solid var(--color-border)",
                    display: "grid",
                    gridTemplateColumns: "1fr auto",
                    gap: "12px",
                    alignItems: "center",
                  }}
                >
                  <div>
                    <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
                      <Badge variant="indigo">{e.domain_a}</Badge>
                      <span style={{ color: "var(--color-text-muted)", fontSize: "11px" }}>×</span>
                      <Badge variant="amber">{e.domain_b}</Badge>
                    </div>
                    <p style={{ margin: "4px 0 0", fontSize: "11px", color: "var(--color-text-muted)" }}>
                      {e.recent_bridges} recent bridge papers / {e.total_bridges} total
                    </p>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "16px", color: "var(--color-amber)", fontWeight: 500 }}>
                      {(e.emergence_ratio * 100).toFixed(0)}%
                    </span>
                    <p style={{ margin: "1px 0 0", fontSize: "10px", color: "var(--color-text-muted)" }}>new</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
