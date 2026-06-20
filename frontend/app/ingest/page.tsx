"use client";

import { useState, useEffect, useRef, useCallback, DragEvent } from "react";
import { api } from "@/lib/api";
import { StatCard, SectionHeader, Badge } from "@/components/ui/primitives";
import { Upload, CheckCircle, Clock, XCircle, Loader, FileText, AlertCircle, ChevronDown, ChevronUp, RefreshCw } from "lucide-react";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

interface Job {
  job_id: string;
  label: string;
  source: string;
  limit?: number;
  status: string;
  submittedAt: string;
}

interface ParsedPaper {
  filename: string;
  page_count: number;
  text_preview: string;
  parsed: {
    title: string;
    abstract: string;
    authors: string[];
    year: number | null;
    doi: string | null;
  };
}

const STATUS_ICON: Record<string, React.ReactNode> = {
  SUCCESS: <CheckCircle size={13} style={{ color: "var(--color-green, #22c55e)" }} />,
  PENDING: <Clock size={13} style={{ color: "var(--color-text-muted)" }} />,
  STARTED: <Loader size={13} style={{ color: "var(--color-indigo)", animation: "spin 1s linear infinite" }} />,
  FAILURE: <XCircle size={13} style={{ color: "#ef4444" }} />,
};

const PRESET_TOPICS = [
  { topic: "machine learning",            source: "openalex", limit: 500 },
  { topic: "federated learning",          source: "arxiv",    limit: 300 },
  { topic: "graph neural networks",       source: "arxiv",    limit: 300 },
  { topic: "natural language processing", source: "openalex", limit: 500 },
  { topic: "drug discovery deep learning",source: "openalex", limit: 300 },
  { topic: "computer vision",             source: "openalex", limit: 300 },
];

// ── PDF Upload panel ──────────────────────────────────────────────────────────

function PdfUploadPanel({ onJobQueued }: { onJobQueued: (job: Job) => void }) {
  const [dragging,     setDragging]     = useState(false);
  const [file,         setFile]         = useState<File | null>(null);
  const [parsing,      setParsing]      = useState(false);
  const [parsed,       setParsed]       = useState<ParsedPaper | null>(null);
  const [parseError,   setParseError]   = useState<string | null>(null);
  const [showPreview,  setShowPreview]  = useState(false);

  // Editable override fields
  const [titleOv,    setTitleOv]    = useState("");
  const [abstractOv, setAbstractOv] = useState("");
  const [authorsOv,  setAuthorsOv]  = useState("");
  const [yearOv,     setYearOv]     = useState("");

  const [submitting,  setSubmitting]  = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);

  const reset = () => {
    setFile(null);
    setParsed(null);
    setParseError(null);
    setShowPreview(false);
    setTitleOv(""); setAbstractOv(""); setAuthorsOv(""); setYearOv("");
    setSubmitError(null);
  };

  const parsePdf = useCallback(async (f: File) => {
    setParsing(true);
    setParsed(null);
    setParseError(null);
    setSubmitError(null);
    const form = new FormData();
    form.append("file", f);
    try {
      const res = await fetch(`${BASE}/ingest/pdf/parse`, { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? "Parse failed");
      setParsed(data);
      // Pre-fill override fields
      setTitleOv(data.parsed.title ?? "");
      setAbstractOv(data.parsed.abstract ?? "");
      setAuthorsOv((data.parsed.authors ?? []).join(", "));
      setYearOv(data.parsed.year ? String(data.parsed.year) : "");
    } catch (e: unknown) {
      setParseError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setParsing(false);
    }
  }, []);

  const onFileChosen = (f: File) => {
    if (!f.name.toLowerCase().endsWith(".pdf")) {
      setParseError("Please select a PDF file.");
      return;
    }
    setFile(f);
    parsePdf(f);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) onFileChosen(f);
  };

  const submitPdf = async () => {
    if (!file || !parsed) return;
    setSubmitting(true);
    setSubmitError(null);
    const form = new FormData();
    form.append("file", file);
    if (titleOv)    form.append("title_override",    titleOv.trim());
    if (abstractOv) form.append("abstract_override", abstractOv.trim());
    if (authorsOv)  form.append("authors_override",  authorsOv.trim());
    if (yearOv)     form.append("year_override",     yearOv.trim());
    try {
      const res = await fetch(`${BASE}/ingest/pdf`, { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? "Upload failed");
      onJobQueued({
        job_id: data.job_id,
        label: titleOv.trim() || parsed.parsed.title || file.name,
        source: "pdf_upload",
        status: "PENDING",
        submittedAt: new Date().toISOString(),
      });
      reset();
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setSubmitting(false);
    }
  };

  const fieldStyle: React.CSSProperties = {
    width: "100%", boxSizing: "border-box",
    background: "var(--color-bg)",
    border: "1px solid var(--color-border)",
    color: "var(--color-text-primary)",
    padding: "7px 10px", fontSize: "12px",
    fontFamily: "var(--font-sans)", outline: "none", borderRadius: "0",
  };
  const labelStyle: React.CSSProperties = {
    margin: "0 0 3px", fontSize: "10px",
    color: "var(--color-text-muted)",
    textTransform: "uppercase", letterSpacing: "0.07em",
  };

  return (
    <div>
      <SectionHeader title="Upload PDF" sub="Parse and ingest a single research paper" />
      <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", padding: "18px", display: "flex", flexDirection: "column", gap: "14px" }}>

        {/* Drop zone */}
        {!parsed && (
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={onDrop}
            onClick={() => inputRef.current?.click()}
            style={{
              border: `2px dashed ${dragging ? "var(--color-indigo)" : "var(--color-border)"}`,
              borderRadius: "4px",
              padding: "32px 20px",
              display: "flex", flexDirection: "column",
              alignItems: "center", justifyContent: "center", gap: "10px",
              cursor: "pointer",
              background: dragging ? "rgba(99,102,241,0.04)" : "transparent",
              transition: "all 0.15s",
            }}
          >
            <FileText size={28} style={{ color: parsing ? "var(--color-indigo)" : "var(--color-text-muted)" }} />
            {parsing ? (
              <span style={{ fontSize: "13px", color: "var(--color-indigo)", fontFamily: "var(--font-mono)" }}>
                Parsing PDF…
              </span>
            ) : file ? (
              <span style={{ fontSize: "13px", color: "var(--color-text-primary)" }}>{file.name}</span>
            ) : (
              <>
                <span style={{ fontSize: "13px", color: "var(--color-text-primary)", fontWeight: 500 }}>
                  Drop a PDF here or click to browse
                </span>
                <span style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>
                  Max 50 MB · text-based PDFs only (not scans)
                </span>
              </>
            )}
            <input
              ref={inputRef}
              type="file"
              accept=".pdf,application/pdf"
              style={{ display: "none" }}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) onFileChosen(f); }}
            />
          </div>
        )}

        {/* Parse error */}
        {parseError && (
          <div style={{ display: "flex", gap: "8px", alignItems: "flex-start", padding: "10px 12px", background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.25)", borderRadius: "4px" }}>
            <AlertCircle size={14} style={{ color: "#ef4444", flexShrink: 0, marginTop: "1px" }} />
            <div>
              <p style={{ margin: 0, fontSize: "12px", color: "#ef4444" }}>{parseError}</p>
              <button onClick={reset} style={{ marginTop: "6px", background: "none", border: "none", color: "var(--color-text-muted)", fontSize: "11px", cursor: "pointer", padding: 0, textDecoration: "underline" }}>
                Try again
              </button>
            </div>
          </div>
        )}

        {/* Parsed result — editable fields */}
        {parsed && (
          <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            {/* File info */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <FileText size={14} style={{ color: "var(--color-indigo)" }} />
                <span style={{ fontSize: "12px", color: "var(--color-text-primary)" }}>{parsed.filename}</span>
                <Badge variant="muted">{parsed.page_count}pp</Badge>
              </div>
              <button onClick={reset} title="Choose different file" style={{ background: "none", border: "1px solid var(--color-border)", color: "var(--color-text-muted)", padding: "3px 8px", fontSize: "11px", cursor: "pointer", display: "flex", alignItems: "center", gap: "4px", borderRadius: "3px" }}>
                <RefreshCw size={11} /> Change
              </button>
            </div>

            {/* Editable fields */}
            <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
              <div>
                <p style={labelStyle}>Title</p>
                <input value={titleOv} onChange={e => setTitleOv(e.target.value)} style={fieldStyle} placeholder="Detected title" />
              </div>
              <div>
                <p style={labelStyle}>Authors (comma-separated)</p>
                <input value={authorsOv} onChange={e => setAuthorsOv(e.target.value)} style={fieldStyle} placeholder="Author One, Author Two" />
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                <div>
                  <p style={labelStyle}>Year</p>
                  <input type="number" value={yearOv} onChange={e => setYearOv(e.target.value)} style={fieldStyle} placeholder="e.g. 2024" min={1900} max={2030} />
                </div>
              </div>
              <div>
                <p style={labelStyle}>Abstract</p>
                <textarea
                  value={abstractOv}
                  onChange={e => setAbstractOv(e.target.value)}
                  rows={6}
                  style={{ ...fieldStyle, resize: "vertical", lineHeight: 1.5 }}
                  placeholder="Paste or edit the abstract here…"
                />
                <p style={{ margin: "3px 0 0", fontSize: "10px", color: "var(--color-text-muted)" }}>
                  {abstractOv.length} chars · need ≥ 50
                </p>
              </div>
            </div>

            {/* Text preview toggle */}
            <button
              onClick={() => setShowPreview(v => !v)}
              style={{ background: "none", border: "none", color: "var(--color-text-muted)", fontSize: "11px", cursor: "pointer", display: "flex", alignItems: "center", gap: "4px", padding: 0, fontFamily: "var(--font-mono)", letterSpacing: "0.05em" }}
            >
              {showPreview ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              {showPreview ? "HIDE RAW TEXT" : "SHOW RAW TEXT PREVIEW"}
            </button>
            {showPreview && (
              <pre style={{ margin: 0, padding: "10px 12px", background: "var(--color-bg)", border: "1px solid var(--color-border)", fontSize: "11px", color: "var(--color-text-muted)", fontFamily: "var(--font-mono)", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: "160px", overflowY: "auto" }}>
                {parsed.text_preview}…
              </pre>
            )}

            {/* Submit error */}
            {submitError && (
              <div style={{ padding: "8px 12px", background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.25)", borderRadius: "4px", fontSize: "12px", color: "#ef4444" }}>
                {submitError}
              </div>
            )}

            {/* Submit button */}
            <button
              onClick={submitPdf}
              disabled={submitting || abstractOv.length < 50 || !titleOv.trim()}
              style={{
                background: "var(--color-indigo)", border: "none",
                color: "white", padding: "10px",
                cursor: submitting || abstractOv.length < 50 || !titleOv.trim() ? "not-allowed" : "pointer",
                fontSize: "12px", fontFamily: "var(--font-mono)", letterSpacing: "0.08em",
                opacity: submitting || abstractOv.length < 50 || !titleOv.trim() ? 0.5 : 1,
                display: "flex", alignItems: "center", justifyContent: "center", gap: "6px",
              }}
            >
              {submitting
                ? <><Loader size={13} style={{ animation: "spin 1s linear infinite" }} /> INGESTING…</>
                : <><Upload size={13} /> INGEST PAPER</>
              }
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function IngestPage() {
  const [tab,     setTab]     = useState<"topic" | "pdf">("topic");
  const [topic,   setTopic]   = useState("");
  const [source,  setSource]  = useState<"openalex" | "arxiv">("openalex");
  const [limit,   setLimit]   = useState(500);
  const [jobs,    setJobs]    = useState<Job[]>([]);
  const [loading, setLoading] = useState(false);
  const [ingestStats, setIngestStats] = useState<{ papers_in_graph: number; papers_this_year: number; most_recent_year: number | null } | null>(null);

  useEffect(() => {
    api.ingest.status().then(setIngestStats).catch(console.error);
  }, []);

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
          } catch { return j; }
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
      setJobs(prev => [{
        job_id: res.job_id, label: t, source: s, limit: l,
        status: "PENDING", submittedAt: new Date().toISOString(),
      }, ...prev]);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  const tabStyle = (active: boolean): React.CSSProperties => ({
    padding: "7px 18px", border: "1px solid",
    borderColor: active ? "var(--color-indigo)" : "var(--color-border)",
    background: active ? "rgba(99,102,241,0.1)" : "var(--color-surface)",
    color: active ? "var(--color-indigo)" : "var(--color-text-muted)",
    fontSize: "12px", fontFamily: "var(--font-mono)", cursor: "pointer",
    letterSpacing: "0.06em",
  });

  const fieldStyle: React.CSSProperties = {
    width: "100%", boxSizing: "border-box",
    background: "var(--color-bg)", border: "1px solid var(--color-border)",
    color: "var(--color-text-primary)", padding: "8px 12px",
    fontSize: "13px", fontFamily: "var(--font-mono)", outline: "none",
  };

  return (
    <div style={{ padding: "32px", maxWidth: "1000px" }}>

      <div style={{ marginBottom: "28px" }}>
        <p style={{ color: "var(--color-indigo)", fontFamily: "var(--font-mono)", fontSize: "11px", letterSpacing: "0.1em", textTransform: "uppercase", margin: "0 0 8px" }}>
          PANDORA / INGEST
        </p>
        <h1 style={{ fontSize: "22px", fontWeight: 600, margin: "0 0 4px" }}>Paper Ingestion</h1>
        <p style={{ color: "var(--color-text-secondary)", margin: 0, fontSize: "13px" }}>
          Seed the knowledge graph from open sources or upload a PDF directly
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

      {/* Tabs */}
      <div style={{ display: "flex", gap: "0", marginBottom: "20px" }}>
        <button onClick={() => setTab("topic")} style={tabStyle(tab === "topic")}>TOPIC SEED</button>
        <button onClick={() => setTab("pdf")}   style={{ ...tabStyle(tab === "pdf"), marginLeft: "-1px" }}>UPLOAD PDF</button>
      </div>

      {/* Topic seed tab */}
      {tab === "topic" && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px", marginBottom: "24px" }}>
          <div>
            <SectionHeader title="Custom Seed" sub="Fetch papers for any topic" />
            <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", padding: "18px", display: "flex", flexDirection: "column", gap: "12px" }}>
              <div>
                <p style={{ margin: "0 0 4px", fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Topic</p>
                <input
                  value={topic} onChange={e => setTopic(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && topic.trim() && handleSeed(topic, source, limit)}
                  placeholder="e.g. quantum computing healthcare"
                  style={fieldStyle}
                />
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "10px" }}>
                <div>
                  <p style={{ margin: "0 0 4px", fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Source</p>
                  <select value={source} onChange={e => setSource(e.target.value as "openalex" | "arxiv")} style={{ ...fieldStyle, fontSize: "12px" }}>
                    <option value="openalex">OpenAlex</option>
                    <option value="arxiv">arXiv</option>
                  </select>
                </div>
                <div>
                  <p style={{ margin: "0 0 4px", fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Limit</p>
                  <input type="number" value={limit} onChange={e => setLimit(Number(e.target.value))} min={100} max={5000} step={100} style={{ ...fieldStyle, fontSize: "12px" }} />
                </div>
              </div>
              <button
                onClick={() => { if (topic.trim()) { handleSeed(topic, source, limit); setTopic(""); } }}
                disabled={loading || !topic.trim()}
                style={{ background: "var(--color-indigo)", border: "none", color: "white", padding: "10px", cursor: "pointer", fontSize: "12px", fontFamily: "var(--font-mono)", letterSpacing: "0.08em", opacity: loading || !topic.trim() ? 0.5 : 1, display: "flex", alignItems: "center", justifyContent: "center", gap: "6px" }}
              >
                <Upload size={13} />
                {loading ? "QUEUING…" : "START INGESTION"}
              </button>
            </div>
          </div>

          <div>
            <SectionHeader title="Preset Topics" sub="One-click seed for foundational areas" />
            <div style={{ display: "flex", flexDirection: "column", gap: "1px", background: "var(--color-border)", border: "1px solid var(--color-border)" }}>
              {PRESET_TOPICS.map(({ topic: t, source: s, limit: l }) => (
                <button key={t} onClick={() => handleSeed(t, s, l)} disabled={loading}
                  style={{ background: "var(--color-surface)", border: "none", padding: "10px 14px", display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer", textAlign: "left" }}>
                  <div>
                    <span style={{ fontSize: "13px", color: "var(--color-text-primary)" }}>{t}</span>
                    <span style={{ marginLeft: "8px", fontSize: "11px", color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
                      {s} / {l.toLocaleString()}
                    </span>
                  </div>
                  <Upload size={12} style={{ color: "var(--color-text-muted)" }} />
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* PDF upload tab */}
      {tab === "pdf" && (
        <div style={{ maxWidth: "560px", marginBottom: "24px" }}>
          <PdfUploadPanel onJobQueued={job => setJobs(prev => [job, ...prev])} />
        </div>
      )}

      {/* Job list */}
      {jobs.length > 0 && (
        <div>
          <SectionHeader title="Ingestion Jobs" sub="Live status of running and completed jobs" />
          <div style={{ display: "flex", flexDirection: "column", gap: "1px", background: "var(--color-border)", border: "1px solid var(--color-border)" }}>
            {jobs.map(j => (
              <div key={j.job_id} style={{ background: "var(--color-surface)", padding: "12px 14px", display: "grid", gridTemplateColumns: "16px 1fr auto", gap: "12px", alignItems: "center" }}>
                {STATUS_ICON[j.status] ?? <Clock size={13} style={{ color: "var(--color-text-muted)" }} />}
                <div>
                  <p style={{ margin: 0, fontSize: "13px", color: "var(--color-text-primary)", fontWeight: 500 }}>{j.label}</p>
                  <p style={{ margin: "2px 0 0", fontSize: "11px", color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
                    {j.source}{j.limit ? ` / ${j.limit.toLocaleString()} papers` : ""} · {new Date(j.submittedAt).toLocaleTimeString()}
                  </p>
                </div>
                <Badge variant={j.status === "SUCCESS" ? "green" : j.status === "FAILURE" ? "muted" : "indigo"}>
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
