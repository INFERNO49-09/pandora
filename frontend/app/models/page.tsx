"use client";

import { useEffect, useState } from "react";
import { SectionHeader, Badge, StatCard, EmptyState, Skeleton } from "@/components/ui/primitives";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer, BarChart, Bar } from "recharts";
import { Cpu, CheckCircle, Clock, Play, RefreshCw } from "lucide-react";
import { api, ModelRecord, ModelMetricSeries } from "@/lib/api";

const TYPE_COLOR: Record<string, string> = {
  graphsage:            "var(--color-indigo)",
  transe:               "var(--color-amber)",
  rotate:               "var(--color-green)",
  embedding_similarity: "var(--color-text-muted)",
};

export default function ModelsPage() {
  const [models,   setModels]   = useState<ModelRecord[]>([]);
  const [active,   setActive]   = useState<ModelRecord[]>([]);
  const [metrics,  setMetrics]  = useState<ModelMetricSeries>({});
  const [loading,  setLoading]  = useState(true);
  const [training, setTraining] = useState(false);
  const [trainForm, setTrainForm] = useState({
    model_type: "graphsage",
    edge_type: "Concept__RELATED_TO__Concept",
    epochs: 50,
    hidden_dim: 256,
  });

  const fetchAll = async () => {
    setLoading(true);
    try {
      const [m, a, met] = await Promise.all([
        api.models.list(30),
        api.models.active(),
        api.models.metrics(),
      ]);
      setModels(m.models || []);
      setActive(a.active_models || []);
      setMetrics(met.series || {});
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAll(); }, []);

  const triggerTraining = async () => {
    setTraining(true);
    try {
      const token = localStorage.getItem("pandora_token");
      const res = await api.models.train(token, trainForm);
      const data = await res.json();
      if (res.ok) {
        alert(`Training queued! Task ID: ${data.task_id}`);
        setTimeout(fetchAll, 5000);
      } else {
        alert(`Error: ${data.detail || "Training failed"}`);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setTraining(false);
    }
  };

  // Build MRR comparison data for bar chart
  const mrrData = active.map(m => ({
    name: `${m.model_type}\n${m.relation_type.split("__")[1]}`,
    mrr: Math.round((m.test_mrr || 0) * 100),
    hits10: Math.round((m.hits_at_10 || 0) * 100),
  }));

  // Build time series for first metric key
  const firstSeriesKey = Object.keys(metrics)[0];
  const timeSeriesData = firstSeriesKey
    ? metrics[firstSeriesKey]
        .filter(m => m.trained_at)
        .slice(-10)
        .map((m, i) => ({
          run: `Run ${i + 1}`,
          mrr: Math.round(m.test_mrr * 100),
          hits10: Math.round(m.hits_at_10 * 100),
        }))
    : [];

  return (
    <div style={{ padding: "32px", maxWidth: "1100px" }}>

      {/* Header */}
      <div style={{ marginBottom: "28px" }}>
        <p style={{ color: "var(--color-indigo)", fontFamily: "var(--font-mono)", fontSize: "11px", letterSpacing: "0.1em", textTransform: "uppercase", margin: "0 0 8px" }}>
          PANDORA / MODELS
        </p>
        <h1 style={{ fontSize: "22px", fontWeight: 600, margin: "0 0 4px" }}>Model Registry</h1>
        <p style={{ color: "var(--color-text-secondary)", margin: 0, fontSize: "13px" }}>
          GraphSAGE and TransE models trained on the knowledge graph
        </p>
      </div>

      {/* Active model summary */}
      {!loading && active.length > 0 && (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "1px", background: "var(--color-border)", border: "1px solid var(--color-border)", marginBottom: "28px" }}>
          <StatCard label="Active Models"  value={active.length}                              accent="indigo" />
          <StatCard label="Best MRR"       value={`${Math.round(Math.max(...active.map(m => m.test_mrr || 0)) * 100)}%`} accent="amber"  mono={false} />
          <StatCard label="Best Hits@10"   value={`${Math.round(Math.max(...active.map(m => m.hits_at_10 || 0)) * 100)}%`} accent="green" mono={false} />
          <StatCard label="Total Trained"  value={models.length}                              accent="indigo" />
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px", marginBottom: "24px" }}>

        {/* MRR bar chart */}
        <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", padding: "18px" }}>
          <SectionHeader title="Active Model Performance" sub="MRR and Hits@10 per model" />
          {loading ? (
            <Skeleton height={200} />
          ) : mrrData.length === 0 ? (
            <EmptyState icon={<Cpu size={24} />} title="No active models" description="Train a model to see performance metrics." />
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={mrrData} margin={{ top: 4, right: 4, bottom: 24, left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="name" tick={{ fontSize: 9, fill: "var(--color-text-muted)" }} />
                <YAxis tick={{ fontSize: 10, fill: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }} unit="%" />
                <Tooltip
                  contentStyle={{ background: "var(--color-surface-2)", border: "1px solid var(--color-border)", fontSize: "12px", fontFamily: "var(--font-mono)" }}
                  formatter={(v: any) => [`${v}%`]}
                />
                <Legend wrapperStyle={{ fontSize: "11px" }} />
                <Bar dataKey="mrr"    name="MRR"     fill="var(--color-indigo)" radius={[2,2,0,0]} />
                <Bar dataKey="hits10" name="Hits@10" fill="var(--color-amber)"  radius={[2,2,0,0]} />
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        {/* MRR over time */}
        <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", padding: "18px" }}>
          <SectionHeader title="MRR Over Training Runs" sub={firstSeriesKey || "No history"} />
          {loading ? (
            <Skeleton height={200} />
          ) : timeSeriesData.length < 2 ? (
            <EmptyState icon={<Clock size={24} />} title="Not enough history" description="Train multiple times to see improvement trends." />
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={timeSeriesData} margin={{ top: 4, right: 4, bottom: 4, left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="run" tick={{ fontSize: 10, fill: "var(--color-text-muted)" }} />
                <YAxis tick={{ fontSize: 10, fill: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }} unit="%" />
                <Tooltip
                  contentStyle={{ background: "var(--color-surface-2)", border: "1px solid var(--color-border)", fontSize: "12px", fontFamily: "var(--font-mono)" }}
                  formatter={(v: any) => [`${v}%`]}
                />
                <Legend wrapperStyle={{ fontSize: "11px" }} />
                <Line type="monotone" dataKey="mrr"    name="MRR"     stroke="var(--color-indigo)" strokeWidth={2} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="hits10" name="Hits@10" stroke="var(--color-amber)"  strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "24px" }}>

        {/* Model table */}
        <div>
          <SectionHeader
            title="All Models"
            action={
              <button onClick={fetchAll} style={{ background: "none", border: "1px solid var(--color-border)", color: "var(--color-text-muted)", padding: "3px 10px", cursor: "pointer", fontSize: "11px", fontFamily: "var(--font-mono)", display: "flex", alignItems: "center", gap: "4px" }}>
                <RefreshCw size={10} /> REFRESH
              </button>
            }
          />
          {loading ? (
            <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
              {[...Array(5)].map((_, i) => <Skeleton key={i} height={36} />)}
            </div>
          ) : models.length === 0 ? (
            <EmptyState icon={<Cpu size={24} />} title="No models trained yet" description="Use the training form to train your first model." />
          ) : (
            <div style={{ border: "1px solid var(--color-border)", background: "var(--color-border)", display: "flex", flexDirection: "column", gap: "1px" }}>
              {/* Header */}
              <div style={{ background: "var(--color-surface-2)", padding: "8px 12px", display: "grid", gridTemplateColumns: "1fr 80px 60px 60px 50px 24px", gap: "8px" }}>
                {["Model", "Relation", "MRR", "H@10", "Dur.", ""].map(h => (
                  <span key={h} style={{ fontSize: "10px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{h}</span>
                ))}
              </div>
              {models.map(m => (
                <div key={m.id} style={{ background: "var(--color-surface)", padding: "8px 12px", display: "grid", gridTemplateColumns: "1fr 80px 60px 60px 50px 24px", gap: "8px", alignItems: "center" }}>
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                      <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: TYPE_COLOR[m.model_type] || "var(--color-text-muted)", flexShrink: 0 }} />
                      <span style={{ fontSize: "12px", color: "var(--color-text-primary)", fontFamily: "var(--font-mono)" }}>{m.model_type}</span>
                    </div>
                    <span style={{ fontSize: "10px", color: "var(--color-text-muted)" }}>
                      {m.trained_at ? new Date(m.trained_at).toLocaleDateString() : "—"}
                    </span>
                  </div>
                  <span style={{ fontSize: "10px", color: "var(--color-text-secondary)" }}>
                    {m.relation_type?.split("__")[1] || "—"}
                  </span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--color-indigo)" }}>
                    {m.test_mrr != null ? `${Math.round(m.test_mrr * 100)}%` : "—"}
                  </span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "12px", color: "var(--color-amber)" }}>
                    {m.hits_at_10 != null ? `${Math.round(m.hits_at_10 * 100)}%` : "—"}
                  </span>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--color-text-muted)" }}>
                    {m.training_duration_s != null ? `${Math.round(m.training_duration_s / 60)}m` : "—"}
                  </span>
                  {m.is_active && <CheckCircle size={12} style={{ color: "var(--color-green)" }} />}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Training form */}
        <div>
          <SectionHeader title="Train New Model" sub="Admin only" />
          <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", padding: "16px", display: "flex", flexDirection: "column", gap: "10px" }}>

            {[
              { label: "Model Type", key: "model_type", type: "select", options: ["graphsage", "transe", "rotate"] },
              { label: "Edge Type", key: "edge_type", type: "select", options: [
                "Concept__RELATED_TO__Concept",
                "Paper__CITES__Paper",
                "Domain__SUBDOMAIN_OF__Domain",
                "Method__VARIANT_OF__Method",
              ]},
              { label: "Epochs", key: "epochs", type: "number" },
              { label: "Hidden Dim", key: "hidden_dim", type: "number" },
            ].map(({ label, key, type, options }) => (
              <div key={key}>
                <p style={{ margin: "0 0 3px", fontSize: "10px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</p>
                {type === "select" ? (
                  <select
                    value={(trainForm as any)[key]}
                    onChange={e => setTrainForm(f => ({ ...f, [key]: e.target.value }))}
                    style={{ width: "100%", background: "var(--color-bg)", border: "1px solid var(--color-border)", color: "var(--color-text-primary)", padding: "6px 8px", fontSize: "12px", fontFamily: "var(--font-mono)", outline: "none" }}
                  >
                    {options?.map(o => <option key={o} value={o}>{o}</option>)}
                  </select>
                ) : (
                  <input
                    type="number"
                    value={(trainForm as any)[key]}
                    onChange={e => setTrainForm(f => ({ ...f, [key]: parseInt(e.target.value) }))}
                    style={{ width: "100%", background: "var(--color-bg)", border: "1px solid var(--color-border)", color: "var(--color-text-primary)", padding: "6px 8px", fontSize: "12px", fontFamily: "var(--font-mono)", outline: "none", boxSizing: "border-box" }}
                  />
                )}
              </div>
            ))}

            <button
              onClick={triggerTraining}
              disabled={training}
              style={{ background: "var(--color-indigo)", border: "none", color: "white", padding: "9px", cursor: "pointer", fontSize: "11px", fontFamily: "var(--font-mono)", letterSpacing: "0.08em", opacity: training ? 0.6 : 1, display: "flex", alignItems: "center", justifyContent: "center", gap: "6px", marginTop: "4px" }}
            >
              <Play size={12} />
              {training ? "QUEUING..." : "QUEUE TRAINING"}
            </button>

            <p style={{ fontSize: "10px", color: "var(--color-text-muted)", margin: "4px 0 0", lineHeight: 1.5 }}>
              Requires admin JWT. Training runs in a Celery worker and may take 1–4 hours depending on graph size.
            </p>
          </div>

          {/* CLI hint */}
          <div style={{ marginTop: "12px", background: "var(--color-surface-2)", border: "1px solid var(--color-border)", padding: "12px" }}>
            <p style={{ margin: "0 0 6px", fontSize: "10px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Or via CLI</p>
            <code style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--color-indigo)", display: "block", lineHeight: 1.8, whiteSpace: "pre-wrap" }}>
              {`python scripts/train.py \\
  --model ${trainForm.model_type} \\
  --edge-type \\
  ${trainForm.edge_type} \\
  --epochs ${trainForm.epochs}`}
            </code>
          </div>
        </div>
      </div>
    </div>
  );
}
