"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { StatCard, SectionHeader, Badge } from "@/components/ui/primitives";
import { Upload, CheckCircle, Clock, XCircle, Loader } from "lucide-react";

interface Job {
  job_id: string;
  topic: string;
  source: string;
  limit: number;
  status: string;
  submittedAt: string;
}

const STATUS_ICON: Record<string, React.ReactNode> = {
  SUCCESS:  <CheckCircle size={13} style={{ color: "var(--color-green)" }} />,
  PENDING:  <Clock size={13} style={{ color: "var(--color-text-muted)" }} />,
  STARTED:  <Loader size={13} style={{ color: "var(--color-indigo)", animation: "spin 1s linear infinite" }} />,
  FAILURE:  <XCircle size={13} style={{ color: "var(--color-red)" }} />,
};

const PRESET_TOPICS = [
  { topic: "machine learning",         source: "openalex", limit: 500  },
  { topic: "federated learning",       source: "arxiv",    limit: 300  },
  { topic: "graph neural networks",    source: "arxiv",    limit: 300  },
  { topic: "natural language processing", source: "openalex", limit: 500 },
  { topic: "drug discovery deep learning", source: "openalex", limit: 300 },
  { topic: "computer vision",          source: "openalex", limit: 300  },
];

export default function IngestPage() {
  const [topic,    setTopic]    = useState("");
  const [source,   setSource]   = useState<"openalex" | "arxiv">("openalex");
  const [limit,    setLimit]    = useState(500);
  const [jobs,     setJobs]     = useState<Job[]>([]);
  const [loading,  setLoading]  = useState(false);
  const [ingestStats, setIngestStats] = useState<any>(null);

  useEffect(() => {
    api.ingest.status().then(setIngestStats).catch(console.error);
  }, []);

  // Poll active jobs
  useEffect(() => {
    const active = jobs.filter((j) => ["PENDING", "STARTED"].includes(j.status));
    if (active.length === 0) return;

    const interval = setInterval(async () => {
      const updated = await Promise.all(
        jobs.map(async (j) => {
          if (!["PENDING", "STARTED"].includes(j.status)) return j;
          try {
            const status = await api.ingest.jobStatus(j.job_id);
            return { ...j, status: status.status };
          } catch {
            return j;
          }
        })
      );
      setJobs(updated);
    }, 3000);

    return () => clearInterval(interval);
  }, [jobs]);

  const handleSeed = async (t: string, s: string, l: number) => {
    setLoading(true);
    try {
      const res = await api.ingest.seed(t, s, l);
      const newJob: Job = {
        job_id: res.job_id,
        topic: t,
        source: s,
        limit: l,
        status: "PENDING",
        submittedAt: new Date().toISOString(),
      };
      setJobs((prev) => [newJob, ...prev]);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const handleCustomSeed = () => {
    if (!topic.trim()) return;
    handleSeed(topic, source, limit);
    setTopic("");
  };

  return (
    <div style={{ padding: "32px", maxWidth: "1000px" }}>

      <div style={{ marginBottom: "28px" }}>
        <p style={{ color: "var(--color-indigo)", fontFamily: "var(--font-mono)", fontSize: "11px", letterSpacing: "0.1em", textTransform: "uppercase", margin: "0 0 8px" }}>
          PANDORA / INGEST
        </p>
        <h1 style={{ fontSize: "22px", fontWeight: 600, margin: "0 0 4px" }}>Paper Ingestion</h1>
        <p style={{ color: "var(--color-text-secondary)", margin: 0, fontSize: "13px" }}>
          Seed the knowledge graph with scientific papers from open sources
        </p>
      </div>

      {/* Stats */}
      {ingestStats && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "1px", background: "var(--color-border)", border: "1px solid var(--color-border)", marginBottom: "28px" }}>
          <StatCard label="Papers in graph" value={ingestStats.papers_in_graph} accent="indigo" />
          <StatCard label="This year" value={ingestStats.papers_this_year} accent="green" />
          <StatCard label="Most recent" value={ingestStats.most_recent_year ?? "—"} accent="amber" mono={false} />
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px", marginBottom: "24px" }}>

        {/* Custom seed */}
        <div>
          <SectionHeader title="Custom Seed" sub="Fetch papers for any topic" />
          <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", padding: "18px", display: "flex", flexDirection: "column", gap: "12px" }}>

            <div>
              <p style={{ margin: "0 0 4px", fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Topic</p>
              <input
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleCustomSeed()}
                placeholder="e.g. quantum computing healthcare"
                style={{
                  width: "100%",
                  background: "var(--color-bg)",
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

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
              <div>
                <p style={{ margin: "0 0 4px", fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Source</p>
                <select
                  value={source}
                  onChange={(e) => setSource(e.target.value as any)}
                  style={{
                    width: "100%",
                    background: "var(--color-bg)",
                    border: "1px solid var(--color-border)",
                    color: "var(--color-text-primary)",
                    padding: "8px 10px",
                    fontSize: "12px",
                    fontFamily: "var(--font-mono)",
                    outline: "none",
                  }}
                >
                  <option value="openalex">OpenAlex</option>
                  <option value="arxiv">arXiv</option>
                </select>
              </div>
              <div>
                <p style={{ margin: "0 0 4px", fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Limit</p>
                <input
                  type="number"
                  value={limit}
                  onChange={(e) => setLimit(Number(e.target.value))}
                  min={100}
                  max={5000}
                  step={100}
                  style={{
                    width: "100%",
                    background: "var(--color-bg)",
                    border: "1px solid var(--color-border)",
                    color: "var(--color-text-primary)",
                    padding: "8px 10px",
                    fontSize: "12px",
                    fontFamily: "var(--font-mono)",
                    outline: "none",
                    boxSizing: "border-box",
                  }}
                />
              </div>
            </div>

            <button
              onClick={handleCustomSeed}
              disabled={loading || !topic.trim()}
              style={{
                background: "var(--color-indigo)",
                border: "none",
                color: "white",
                padding: "10px",
                cursor: "pointer",
                fontSize: "12px",
                fontFamily: "var(--font-mono)",
                letterSpacing: "0.08em",
                opacity: loading || !topic.trim() ? 0.5 : 1,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "6px",
              }}
            >
              <Upload size={13} />
              {loading ? "QUEUING..." : "START INGESTION"}
            </button>
          </div>
        </div>

        {/* Preset topics */}
        <div>
          <SectionHeader title="Preset Topics" sub="One-click seed for foundational areas" />
          <div style={{ display: "flex", flexDirection: "column", gap: "1px", background: "var(--color-border)", border: "1px solid var(--color-border)" }}>
            {PRESET_TOPICS.map(({ topic: t, source: s, limit: l }) => (
              <button
                key={t}
                onClick={() => handleSeed(t, s, l)}
                disabled={loading}
                style={{
                  background: "var(--color-surface)",
                  border: "none",
                  padding: "10px 14px",
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  cursor: "pointer",
                  textAlign: "left",
                }}
              >
                <div>
                  <span style={{ fontSize: "13px", color: "var(--color-text-primary)" }}>{t}</span>
                  <span style={{ marginLeft: "8px", fontSize: "11px", color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
                    {s} / {l.toLocaleString()} papers
                  </span>
                </div>
                <Upload size={12} style={{ color: "var(--color-text-muted)" }} />
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Job list */}
      {jobs.length > 0 && (
        <div>
          <SectionHeader title="Ingestion Jobs" sub="Live status of running and completed jobs" />
          <div style={{ display: "flex", flexDirection: "column", gap: "1px", background: "var(--color-border)", border: "1px solid var(--color-border)" }}>
            {jobs.map((j) => (
              <div
                key={j.job_id}
                style={{
                  background: "var(--color-surface)",
                  padding: "12px 14px",
                  display: "grid",
                  gridTemplateColumns: "16px 1fr auto",
                  gap: "12px",
                  alignItems: "center",
                }}
              >
                {STATUS_ICON[j.status] ?? <Clock size={13} style={{ color: "var(--color-text-muted)" }} />}
                <div>
                  <p style={{ margin: 0, fontSize: "13px", color: "var(--color-text-primary)", fontWeight: 500 }}>{j.topic}</p>
                  <p style={{ margin: "2px 0 0", fontSize: "11px", color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
                    {j.source} / {j.limit.toLocaleString()} papers / {new Date(j.submittedAt).toLocaleTimeString()}
                  </p>
                </div>
                <Badge
                  variant={
                    j.status === "SUCCESS" ? "green" :
                    j.status === "FAILURE" ? "muted" :
                    "indigo"
                  }
                >
                  {j.status}
                </Badge>
              </div>
            ))}
          </div>
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
