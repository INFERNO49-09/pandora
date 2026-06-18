import { api } from "@/lib/api";
import { Badge, ScoreBar, SectionHeader } from "@/components/ui/primitives";
import { scoreColor, scoreLabel, timeAgo } from "@/lib/utils";
import Link from "next/link";
import { ArrowLeft, BookOpen, FlaskConical, Lightbulb, AlertTriangle } from "lucide-react";
import { notFound } from "next/navigation";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function OpportunityDetailPage({ params }: Props) {
  const { id } = await params;

  let opp;
  try {
    opp = await api.discovery.opportunity(id);
  } catch {
    notFound();
  }

  const score = opp.opportunity_score;

  return (
    <div style={{ padding: "32px", maxWidth: "900px" }}>

      {/* Back */}
      <Link
        href="/discover"
        style={{ display: "inline-flex", alignItems: "center", gap: "6px", color: "var(--color-text-muted)", fontSize: "12px", textDecoration: "none", marginBottom: "24px", fontFamily: "var(--font-mono)" }}
      >
        <ArrowLeft size={12} /> DISCOVER
      </Link>

      {/* Title block */}
      <div style={{ marginBottom: "28px" }}>
        <div style={{ display: "flex", gap: "8px", marginBottom: "12px" }}>
          <Badge variant="indigo">{opp.domain_a}</Badge>
          <span style={{ color: "var(--color-text-muted)", alignSelf: "center" }}>×</span>
          <Badge variant="amber">{opp.domain_b}</Badge>
        </div>
        <h1 style={{ fontSize: "22px", fontWeight: 600, margin: "0 0 8px", lineHeight: 1.3 }}>
          {opp.title}
        </h1>
        <div style={{ display: "flex", gap: "16px", alignItems: "center" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: "6px" }}>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: "32px",
                fontWeight: 500,
                color: scoreColor(score),
                lineHeight: 1,
              }}
            >
              {Math.round(score * 100)}
            </span>
            <span style={{ color: "var(--color-text-muted)", fontSize: "12px" }}>opportunity score</span>
          </div>
          <div
            style={{
              padding: "3px 10px",
              fontSize: "11px",
              fontFamily: "var(--font-mono)",
              background: `${scoreColor(score)}18`,
              color: scoreColor(score),
              border: `1px solid ${scoreColor(score)}40`,
            }}
          >
            {scoreLabel(score).toUpperCase()} POTENTIAL
          </div>
          <span style={{ fontSize: "11px", color: "var(--color-text-muted)", marginLeft: "auto", fontFamily: "var(--font-mono)" }}>
            Discovered {timeAgo(opp.generated_at)}
          </span>
        </div>
      </div>

      {/* Score breakdown */}
      <div
        style={{
          background: "var(--color-surface)",
          border: "1px solid var(--color-border)",
          padding: "18px",
          marginBottom: "24px",
        }}
      >
        <SectionHeader title="Score Breakdown" />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "14px" }}>
          {[
            { label: "Novelty",      val: opp.novelty_score,      desc: "How unexplored is this connection?" },
            { label: "Impact",       val: opp.impact_score,       desc: "How important are these domains?" },
            { label: "Feasibility",  val: opp.feasibility_score,  desc: "Shared methods bridge the gap?" },
            { label: "Velocity",     val: opp.velocity_score,     desc: "Are both domains actively publishing?" },
          ].map(({ label, val, desc }) => (
            <div key={label}>
              <ScoreBar score={val ?? 0} label={label} height={3} />
              <p style={{ margin: "4px 0 0", fontSize: "11px", color: "var(--color-text-muted)" }}>{desc}</p>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "16px", marginBottom: "16px" }}>

        {/* Hypothesis */}
        {opp.hypothesis && (
          <div
            style={{
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              borderLeft: "3px solid var(--color-indigo)",
              padding: "18px",
            }}
          >
            <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "10px" }}>
              <Lightbulb size={14} style={{ color: "var(--color-indigo)" }} />
              <span style={{ fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--color-indigo)" }}>
                Hypothesis
              </span>
            </div>
            <p style={{ margin: 0, fontSize: "13px", lineHeight: 1.6, color: "var(--color-text-primary)" }}>
              {opp.hypothesis}
            </p>
          </div>
        )}

        {/* Rationale */}
        {opp.hypothesis_rationale && (
          <div
            style={{
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              padding: "18px",
            }}
          >
            <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "10px" }}>
              <BookOpen size={14} style={{ color: "var(--color-text-secondary)" }} />
              <span style={{ fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--color-text-secondary)" }}>
                Rationale
              </span>
            </div>
            <p style={{ margin: 0, fontSize: "13px", lineHeight: 1.6, color: "var(--color-text-secondary)" }}>
              {opp.hypothesis_rationale}
            </p>
          </div>
        )}
      </div>

      {/* Experimental approach */}
      {opp.experimental_approach && (
        <div
          style={{
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
            borderLeft: "3px solid var(--color-amber)",
            padding: "18px",
            marginBottom: "16px",
          }}
        >
          <div style={{ display: "flex", gap: "8px", alignItems: "center", marginBottom: "10px" }}>
            <FlaskConical size={14} style={{ color: "var(--color-amber)" }} />
            <span style={{ fontSize: "11px", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.08em", color: "var(--color-amber)" }}>
              Experimental Approach
            </span>
          </div>
          <p style={{ margin: 0, fontSize: "13px", lineHeight: 1.6, color: "var(--color-text-secondary)", whiteSpace: "pre-line" }}>
            {opp.experimental_approach}
          </p>
        </div>
      )}

      {/* Bridge concepts */}
      {opp.bridge_concepts && opp.bridge_concepts.length > 0 && (
        <div
          style={{
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
            padding: "18px",
            marginBottom: "16px",
          }}
        >
          <SectionHeader title="Bridge Concepts" sub="Shared concepts that could connect these domains" />
          <div style={{ display: "flex", gap: "6px", flexWrap: "wrap" }}>
            {opp.bridge_concepts.map((c) => (
              <Badge key={c} variant="muted">{c}</Badge>
            ))}
          </div>
        </div>
      )}

      {/* Supporting papers */}
      {Array.isArray((opp as any).supporting_papers) && (opp as any).supporting_papers.length > 0 && (
        <div
          style={{
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
            padding: "18px",
          }}
        >
          <SectionHeader
            title="Supporting Papers"
            sub={`${(opp as any).supporting_papers.length} papers provide evidence for this opportunity`}
          />
          <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            {(opp as any).supporting_papers.slice(0, 8).map((p: any) => (
              <div
                key={p.id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "baseline",
                  padding: "8px 0",
                  borderBottom: "1px solid var(--color-border)",
                  gap: "12px",
                }}
              >
                <p style={{ margin: 0, fontSize: "13px", color: "var(--color-text-primary)", lineHeight: 1.4, flex: 1 }}>
                  {p.title}
                </p>
                <div style={{ display: "flex", gap: "8px", flexShrink: 0 }}>
                  {p.year && (
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--color-text-muted)" }}>
                      {p.year}
                    </span>
                  )}
                  {p.citations != null && (
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--color-text-muted)" }}>
                      ★ {p.citations}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
