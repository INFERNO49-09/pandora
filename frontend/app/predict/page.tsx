"use client";

import { useState } from "react";
import { api, type SearchResult } from "@/lib/api";
import { Badge, SectionHeader, EmptyState } from "@/components/ui/primitives";
import { Zap, Search, ArrowRight } from "lucide-react";

interface Prediction {
  source_name: string;
  target_node_id: string;
  target_name: string;
  predicted_relation: string;
  confidence: number;
  model_name: string;
}

export default function PredictPage() {
  const [query,       setQuery]       = useState("");
  const [results,     setResults]     = useState<SearchResult[]>([]);
  const [searching,   setSearching]   = useState(false);
  const [selected,    setSelected]    = useState<SearchResult | null>(null);
  const [predictions, setPredictions] = useState<Prediction[]>([]);
  const [predicting,  setPredicting]  = useState(false);

  const [domainA, setDomainA] = useState("");
  const [domainB, setDomainB] = useState("");
  const [scoring, setScoring] = useState(false);
  const [score,   setScore]   = useState<any>(null);

  const handleSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    try {
      const res = await api.graph.search(query);
      setResults(res.results.filter((r) => ["Concept", "Domain", "Method"].includes(r.type)));
    } catch (e) {
      console.error(e);
    } finally {
      setSearching(false);
    }
  };

  const handleSelect = async (node: SearchResult) => {
    setSelected(node);
    setResults([]);
    setQuery(node.label);
    setPredicting(true);
    try {
      const res = await api.predict.links(node.id, node.type, 15);
      setPredictions(res.predictions as Prediction[]);
    } catch (e) {
      console.error(e);
    } finally {
      setPredicting(false);
    }
  };

  const handleScore = async () => {
    if (!domainA.trim() || !domainB.trim()) return;
    setScoring(true);
    setScore(null);
    try {
      const res = await api.discovery.score(domainA, domainB);
      setScore(res);
    } catch (e) {
      console.error(e);
    } finally {
      setScoring(false);
    }
  };

  const scoreColor = (s: number) => s >= 0.75 ? "var(--color-amber)" : s >= 0.55 ? "var(--color-indigo)" : "var(--color-text-muted)";

  return (
    <div style={{ padding: "32px", maxWidth: "1000px" }}>

      <div style={{ marginBottom: "28px" }}>
        <p style={{ color: "var(--color-indigo)", fontFamily: "var(--font-mono)", fontSize: "11px", letterSpacing: "0.1em", textTransform: "uppercase", margin: "0 0 8px" }}>
          PANDORA / PREDICT
        </p>
        <h1 style={{ fontSize: "22px", fontWeight: 600, margin: "0 0 4px" }}>Link Prediction</h1>
        <p style={{ color: "var(--color-text-secondary)", margin: 0, fontSize: "13px" }}>
          Find missing connections and score potential research opportunities
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px" }}>

        {/* Node search + predictions */}
        <div>
          <SectionHeader title="Predict Missing Links" sub="Search a concept or domain to find missing connections" />

          <div style={{ display: "flex", gap: "8px", marginBottom: "8px" }}>
            <div
              style={{
                flex: 1,
                display: "flex",
                alignItems: "center",
                gap: "8px",
                background: "var(--color-surface)",
                border: "1px solid var(--color-border)",
                padding: "8px 12px",
              }}
            >
              <Search size={13} style={{ color: "var(--color-text-muted)", flexShrink: 0 }} />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                placeholder="e.g. Federated Learning, Graph Neural Networks..."
                style={{ flex: 1, background: "none", border: "none", outline: "none", color: "var(--color-text-primary)", fontSize: "13px", fontFamily: "var(--font-mono)" }}
              />
            </div>
            <button
              onClick={handleSearch}
              disabled={searching}
              style={{
                background: "var(--color-indigo)",
                border: "none",
                color: "white",
                padding: "8px 16px",
                cursor: "pointer",
                fontSize: "12px",
                fontFamily: "var(--font-mono)",
                opacity: searching ? 0.6 : 1,
              }}
            >
              {searching ? "..." : "SEARCH"}
            </button>
          </div>

          {/* Search results dropdown */}
          {results.length > 0 && (
            <div style={{ border: "1px solid var(--color-border)", background: "var(--color-surface)", marginBottom: "12px" }}>
              {results.slice(0, 8).map((r) => (
                <button
                  key={r.id}
                  onClick={() => handleSelect(r)}
                  style={{
                    width: "100%",
                    background: "none",
                    border: "none",
                    borderBottom: "1px solid var(--color-border)",
                    padding: "10px 12px",
                    display: "flex",
                    gap: "10px",
                    alignItems: "center",
                    cursor: "pointer",
                    textAlign: "left",
                  }}
                >
                  <Badge variant={r.type === "Domain" ? "amber" : r.type === "Method" ? "indigo" : "muted"}>{r.type}</Badge>
                  <span style={{ fontSize: "13px", color: "var(--color-text-primary)" }}>{r.label}</span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--color-text-muted)", marginLeft: "auto" }}>
                    score {r.score.toFixed(2)}
                  </span>
                </button>
              ))}
            </div>
          )}

          {/* Predictions list */}
          {predicting ? (
            <div style={{ padding: "32px", textAlign: "center", color: "var(--color-text-muted)", fontSize: "13px" }}>
              Running prediction model...
            </div>
          ) : selected && predictions.length > 0 ? (
            <div>
              <p style={{ fontSize: "11px", color: "var(--color-text-muted)", margin: "0 0 8px", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                Predicted connections for <span style={{ color: "var(--color-text-primary)" }}>{selected.label}</span>
              </p>
              <div style={{ display: "flex", flexDirection: "column", gap: "1px", background: "var(--color-border)", border: "1px solid var(--color-border)" }}>
                {predictions.map((p, i) => (
                  <div
                    key={i}
                    style={{
                      background: "var(--color-surface)",
                      padding: "10px 12px",
                      display: "grid",
                      gridTemplateColumns: "1fr auto",
                      gap: "12px",
                      alignItems: "center",
                    }}
                  >
                    <div>
                      <p style={{ margin: 0, fontSize: "13px", color: "var(--color-text-primary)", fontWeight: 500 }}>{p.target_name}</p>
                      <p style={{ margin: "2px 0 0", fontSize: "11px", color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
                        {p.predicted_relation}
                      </p>
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: "15px", fontWeight: 500, color: scoreColor(p.confidence) }}>
                        {(p.confidence * 100).toFixed(0)}
                      </span>
                      <p style={{ margin: "1px 0 0", fontSize: "10px", color: "var(--color-text-muted)" }}>confidence</p>
                    </div>
                  </div>
                ))}
              </div>
              <p style={{ fontSize: "11px", color: "var(--color-text-muted)", margin: "8px 0 0" }}>
                Model: <span style={{ fontFamily: "var(--font-mono)", color: "var(--color-indigo)" }}>{predictions[0]?.model_name}</span>
              </p>
            </div>
          ) : selected ? (
            <EmptyState title="No predictions found" description="Try a concept with more connections in the graph." />
          ) : null}
        </div>

        {/* Domain pair scorer */}
        <div>
          <SectionHeader title="Score a Domain Pair" sub="Run CARGS on any two research domains" />

          <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginBottom: "12px" }}>
            {[
              { label: "Domain A", val: domainA, set: setDomainA, placeholder: "e.g. Federated Learning" },
              { label: "Domain B", val: domainB, set: setDomainB, placeholder: "e.g. Cancer Imaging" },
            ].map(({ label, val, set, placeholder }) => (
              <div key={label}>
                <p style={{ margin: "0 0 4px", fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</p>
                <input
                  value={val}
                  onChange={(e) => set(e.target.value)}
                  placeholder={placeholder}
                  style={{
                    width: "100%",
                    background: "var(--color-surface)",
                    border: "1px solid var(--color-border)",
                    color: "var(--color-text-primary)",
                    padding: "8px 12px",
                    fontSize: "13px",
                    fontFamily: "var(--font-mono)",
                    outline: "none",
                    boxSizing: "border-box",
                  }}
                />
              </div>
            ))}
            <button
              onClick={handleScore}
              disabled={scoring || !domainA.trim() || !domainB.trim()}
              style={{
                background: "var(--color-indigo)",
                border: "none",
                color: "white",
                padding: "10px",
                cursor: "pointer",
                fontSize: "12px",
                fontFamily: "var(--font-mono)",
                letterSpacing: "0.08em",
                opacity: scoring || !domainA.trim() || !domainB.trim() ? 0.5 : 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "6px",
              }}
            >
              <Zap size={13} />
              {scoring ? "SCORING..." : "RUN CARGS SCORING"}
            </button>
          </div>

          {/* Score result */}
          {score && (
            <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", padding: "16px", animation: "fade-in 0.2s ease" }}>
              <div style={{ display: "flex", gap: "8px", marginBottom: "14px" }}>
                <Badge variant="indigo">{score.domain_a}</Badge>
                <span style={{ color: "var(--color-text-muted)", alignSelf: "center" }}>×</span>
                <Badge variant="amber">{score.domain_b}</Badge>
              </div>

              <div style={{ display: "flex", alignItems: "baseline", gap: "8px", marginBottom: "16px" }}>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: "36px", fontWeight: 500, color: scoreColor(score.score.opportunity_score), lineHeight: 1 }}>
                  {Math.round(score.score.opportunity_score * 100)}
                </span>
                <span style={{ color: "var(--color-text-muted)", fontSize: "12px" }}>opportunity score</span>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
                {[
                  { label: "Novelty",           val: score.score.novelty_score },
                  { label: "Impact",            val: score.score.impact_score },
                  { label: "Feasibility",       val: score.score.feasibility_score },
                  { label: "Velocity",          val: score.score.velocity_score },
                  { label: "Semantic Proximity", val: score.score.embedding_proximity },
                ].map(({ label, val }) => (
                  <div key={label}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "3px" }}>
                      <span style={{ fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</span>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: scoreColor(val ?? 0) }}>{Math.round((val ?? 0) * 100)}</span>
                    </div>
                    <div style={{ height: "2px", background: "var(--color-border-2)", position: "relative" }}>
                      <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${(val ?? 0) * 100}%`, background: `linear-gradient(90deg, var(--color-indigo), ${scoreColor(val ?? 0)})` }} />
                    </div>
                  </div>
                ))}
              </div>

              <p style={{ margin: "12px 0 0", fontSize: "11px", color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
                Hypothesis generation: {score.hypothesis_generation}
              </p>
            </div>
          )}
        </div>
      </div>

      <style>{`
        @keyframes fade-in {
          from { opacity: 0; transform: translateY(4px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
