"use client";

import { useState, useEffect, useCallback } from "react";
import { SectionHeader, Badge } from "@/components/ui/primitives";
import {
  Cpu,
  CloudCog,
  Laptop,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Loader,
  RefreshCw,
  Send,
  Zap,
} from "lucide-react";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

interface LlmStatus {
  provider: "nim" | "local";
  chat_model: string;
  embed_model: string;
  base_url: string;
  status: "ok" | "unreachable" | "model_not_pulled" | "unknown";
  latency_ms?: number;
  available_models?: string[];
  error?: string;
  warning?: string;
  hint?: string;
  is_local: boolean;
  embed_dim: number;
  note: string;
}

interface TestResult {
  ok: boolean;
  provider: string;
  model: string;
  response?: string;
  error?: string;
  latency_ms: number;
}

const STATUS_META: Record<string, { icon: React.ReactNode; color: string; label: string }> = {
  ok:               { icon: <CheckCircle2 size={14} />, color: "var(--color-green, #22c55e)", label: "Connected"      },
  unreachable:      { icon: <XCircle size={14} />,       color: "#ef4444",                      label: "Unreachable"   },
  model_not_pulled: { icon: <AlertTriangle size={14} />, color: "var(--color-amber)",            label: "Model missing" },
  unknown:          { icon: <Loader size={14} />,        color: "var(--color-text-muted)",       label: "Checking…"     },
};

export default function SettingsPage() {
  const [status,    setStatus]    = useState<LlmStatus | null>(null);
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState<string | null>(null);
  const [testing,   setTesting]   = useState(false);
  const [testResult,setTestResult]= useState<TestResult | null>(null);
  const [testPrompt,setTestPrompt]= useState("Say 'pandora is online' and nothing else.");

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${BASE}/system/llm`);
      if (!res.ok) throw new Error(`Status check failed (${res.status})`);
      const data = await res.json();
      setStatus(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not reach backend");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  const runTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await fetch(`${BASE}/system/llm/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: testPrompt }),
      });
      const data = await res.json();
      setTestResult(data);
    } catch (e: unknown) {
      setTestResult({
        ok: false,
        provider: status?.provider ?? "unknown",
        model: status?.chat_model ?? "unknown",
        error: e instanceof Error ? e.message : "Request failed",
        latency_ms: 0,
      });
    } finally {
      setTesting(false);
    }
  };

  const meta = status ? STATUS_META[status.status] ?? STATUS_META.unknown : STATUS_META.unknown;

  const cardStyle: React.CSSProperties = {
    background: "var(--color-surface)",
    border: "1px solid var(--color-border)",
    padding: "18px",
  };
  const rowStyle: React.CSSProperties = {
    display: "flex", justifyContent: "space-between", alignItems: "center",
    padding: "9px 0", borderBottom: "1px solid var(--color-border)",
  };
  const labelStyle: React.CSSProperties = { fontSize: "12px", color: "var(--color-text-muted)" };
  const valueStyle: React.CSSProperties = { fontSize: "12px", color: "var(--color-text-primary)", fontFamily: "var(--font-mono)" };

  return (
    <div style={{ padding: "32px", maxWidth: "760px" }}>
      <div style={{ marginBottom: "28px" }}>
        <p style={{ color: "var(--color-indigo)", fontFamily: "var(--font-mono)", fontSize: "11px", letterSpacing: "0.1em", textTransform: "uppercase", margin: "0 0 8px" }}>
          PANDORA / SETTINGS
        </p>
        <h1 style={{ fontSize: "22px", fontWeight: 600, margin: "0 0 4px" }}>System Settings</h1>
        <p style={{ color: "var(--color-text-secondary)", margin: 0, fontSize: "13px" }}>
          LLM provider configuration and connectivity
        </p>
      </div>

      <SectionHeader title="LLM Provider" sub="Switch between NVIDIA NIM and a local model in your .env file" />

      <div style={{ ...cardStyle, marginBottom: "24px" }}>
        {loading ? (
          <div style={{ display: "flex", alignItems: "center", gap: "8px", color: "var(--color-text-muted)", fontSize: "13px" }}>
            <Loader size={14} style={{ animation: "spin 1s linear infinite" }} />
            Checking provider status…
          </div>
        ) : error ? (
          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            <div style={{ display: "flex", gap: "8px", alignItems: "center", color: "#ef4444", fontSize: "13px" }}>
              <XCircle size={14} /> {error}
            </div>
            <button onClick={fetchStatus} style={{ alignSelf: "flex-start", background: "none", border: "1px solid var(--color-border)", color: "var(--color-text-muted)", padding: "5px 10px", fontSize: "11px", cursor: "pointer", borderRadius: "4px", display: "flex", alignItems: "center", gap: "5px" }}>
              <RefreshCw size={11} /> Retry
            </button>
          </div>
        ) : status && (
          <>
            {/* Header row: provider + status pill */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                {status.is_local
                  ? <Laptop size={20} style={{ color: "var(--color-indigo)" }} />
                  : <CloudCog size={20} style={{ color: "var(--color-indigo)" }} />
                }
                <div>
                  <p style={{ margin: 0, fontSize: "15px", fontWeight: 600, color: "var(--color-text-primary)" }}>
                    {status.is_local ? "Local Model" : "NVIDIA NIM"}
                  </p>
                  <p style={{ margin: "2px 0 0", fontSize: "11px", color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
                    {status.base_url}
                  </p>
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: "6px", color: meta.color, fontSize: "12px", fontFamily: "var(--font-mono)" }}>
                {meta.icon} {meta.label}
                {status.latency_ms != null && <span style={{ color: "var(--color-text-muted)" }}>· {status.latency_ms}ms</span>}
              </div>
            </div>

            {/* Warnings / errors */}
            {(status.error || status.warning) && (
              <div style={{
                display: "flex", gap: "8px", alignItems: "flex-start",
                padding: "10px 12px", marginBottom: "14px",
                background: status.status === "model_not_pulled" ? "rgba(245,158,11,0.08)" : "rgba(239,68,68,0.08)",
                border: `1px solid ${status.status === "model_not_pulled" ? "rgba(245,158,11,0.25)" : "rgba(239,68,68,0.25)"}`,
                borderRadius: "4px",
              }}>
                <AlertTriangle size={14} style={{ color: status.status === "model_not_pulled" ? "var(--color-amber)" : "#ef4444", flexShrink: 0, marginTop: "1px" }} />
                <div>
                  <p style={{ margin: 0, fontSize: "12px", color: "var(--color-text-primary)" }}>
                    {status.warning || status.error}
                  </p>
                  {status.hint && (
                    <p style={{ margin: "4px 0 0", fontSize: "11px", color: "var(--color-text-muted)" }}>{status.hint}</p>
                  )}
                </div>
              </div>
            )}

            {/* Details table */}
            <div style={rowStyle}>
              <span style={labelStyle}>Chat model</span>
              <span style={valueStyle}>{status.chat_model}</span>
            </div>
            <div style={rowStyle}>
              <span style={labelStyle}>Embedding model</span>
              <span style={valueStyle}>{status.embed_model} ({status.embed_dim}-dim)</span>
            </div>
            {status.available_models && status.available_models.length > 0 && (
              <div style={{ ...rowStyle, alignItems: "flex-start" }}>
                <span style={labelStyle}>Available locally</span>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "4px", justifyContent: "flex-end", maxWidth: "70%" }}>
                  {status.available_models.map(m => <Badge key={m} variant="muted">{m}</Badge>)}
                </div>
              </div>
            )}
            <div style={{ ...rowStyle, borderBottom: "none" }}>
              <span style={labelStyle}>Provider switch</span>
              <span style={{ fontSize: "11px", color: "var(--color-text-muted)" }}>via <code style={{ fontFamily: "var(--font-mono)" }}>LLM_PROVIDER</code> in .env</span>
            </div>

            <button onClick={fetchStatus} style={{ marginTop: "10px", background: "none", border: "1px solid var(--color-border)", color: "var(--color-text-muted)", padding: "5px 10px", fontSize: "11px", cursor: "pointer", borderRadius: "4px", display: "flex", alignItems: "center", gap: "5px" }}>
              <RefreshCw size={11} /> Refresh status
            </button>
          </>
        )}
      </div>

      {/* Test prompt panel */}
      {status && status.status !== "unreachable" && (
        <>
          <SectionHeader title="Test Connection" sub="Send a small prompt through the active model" />
          <div style={cardStyle}>
            <div style={{ display: "flex", gap: "8px", marginBottom: "12px" }}>
              <input
                value={testPrompt}
                onChange={e => setTestPrompt(e.target.value)}
                onKeyDown={e => e.key === "Enter" && !testing && runTest()}
                style={{
                  flex: 1, boxSizing: "border-box",
                  background: "var(--color-bg)", border: "1px solid var(--color-border)",
                  color: "var(--color-text-primary)", padding: "8px 12px",
                  fontSize: "12px", fontFamily: "var(--font-mono)", outline: "none",
                }}
              />
              <button
                onClick={runTest}
                disabled={testing}
                style={{
                  background: "var(--color-indigo)", border: "none", color: "white",
                  padding: "8px 16px", cursor: testing ? "wait" : "pointer",
                  fontSize: "12px", fontFamily: "var(--font-mono)",
                  display: "flex", alignItems: "center", gap: "6px",
                  opacity: testing ? 0.6 : 1,
                }}
              >
                {testing ? <Loader size={13} style={{ animation: "spin 1s linear infinite" }} /> : <Send size={13} />}
                {testing ? "RUNNING" : "RUN"}
              </button>
            </div>

            {testResult && (
              <div style={{
                padding: "12px 14px",
                background: testResult.ok ? "rgba(34,197,94,0.06)" : "rgba(239,68,68,0.06)",
                border: `1px solid ${testResult.ok ? "rgba(34,197,94,0.2)" : "rgba(239,68,68,0.2)"}`,
                borderRadius: "4px",
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: testResult.response || testResult.error ? "8px" : 0 }}>
                  {testResult.ok ? <CheckCircle2 size={13} style={{ color: "var(--color-green, #22c55e)" }} /> : <XCircle size={13} style={{ color: "#ef4444" }} />}
                  <span style={{ fontSize: "12px", color: "var(--color-text-primary)" }}>
                    {testResult.ok ? "Success" : "Failed"}
                  </span>
                  <span style={{ fontSize: "11px", color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
                    · {testResult.model} · {testResult.latency_ms}ms
                  </span>
                </div>
                {testResult.response && (
                  <p style={{ margin: 0, fontSize: "12px", color: "var(--color-text-secondary)", fontFamily: "var(--font-mono)", lineHeight: 1.5 }}>
                    &quot;{testResult.response}&quot;
                  </p>
                )}
                {testResult.error && (
                  <p style={{ margin: 0, fontSize: "12px", color: "#ef4444" }}>{testResult.error}</p>
                )}
              </div>
            )}
          </div>
        </>
      )}

      {/* Quickstart help for local */}
      {status?.is_local && status.status !== "ok" && (
        <div style={{ marginTop: "24px" }}>
          <SectionHeader title="Local Setup" sub="Quick steps to get a local model running" />
          <div style={{ ...cardStyle, display: "flex", flexDirection: "column", gap: "8px" }}>
            {[
              "Install Ollama from https://ollama.com",
              `Run: ollama pull ${status.chat_model}`,
              `Run: ollama pull ${status.embed_model}`,
              "Ollama serves automatically on localhost:11434 — no extra step needed",
              "Refresh this page once the models are pulled",
            ].map((step, i) => (
              <div key={i} style={{ display: "flex", gap: "10px", alignItems: "flex-start" }}>
                <span style={{ fontSize: "11px", fontFamily: "var(--font-mono)", color: "var(--color-indigo)", flexShrink: 0, width: "16px" }}>{i + 1}.</span>
                <span style={{ fontSize: "12px", color: "var(--color-text-secondary)", fontFamily: "var(--font-mono)" }}>{step}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
