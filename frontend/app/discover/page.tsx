import { api } from "@/lib/api";
import { Badge, ScoreBar, SectionHeader, EmptyState } from "@/components/ui/primitives";
import { scoreColor, timeAgo } from "@/lib/utils";
import Link from "next/link";
import { Telescope, ArrowRight } from "lucide-react";

interface Props {
  searchParams: Promise<{ domain?: string; sort?: string; min?: string }>;
}

export default async function DiscoverPage({ searchParams }: Props) {
  const params = await searchParams;
  const domain  = params.domain ?? undefined;
  const sort    = params.sort ?? "opportunity_score";
  const minScore = parseFloat(params.min ?? "0.5");

  let data;
  try {
    data = await api.discovery.opportunities({
      domain, sort_by: sort, min_score: minScore, limit: 50,
    });
  } catch {
    data = { opportunities: [], total: 0, offset: 0, limit: 50 };
  }

  const { opportunities, total } = data;

  return (
    <div style={{ padding: "32px", maxWidth: "1000px" }}>

      {/* Header */}
      <div style={{ marginBottom: "28px" }}>
        <p style={{ color: "var(--color-indigo)", fontFamily: "var(--font-mono)", fontSize: "11px", letterSpacing: "0.1em", textTransform: "uppercase", margin: "0 0 8px" }}>
          PANDORA / DISCOVER
        </p>
        <h1 style={{ fontSize: "22px", fontWeight: 600, margin: "0 0 4px" }}>
          Research Opportunities
        </h1>
        <p style={{ color: "var(--color-text-secondary)", margin: 0, fontSize: "13px" }}>
          {total > 0 ? `${total} gaps detected across the knowledge graph` : "No opportunities discovered yet"}
        </p>
      </div>

      {/* Filters bar */}
      <FilterBar current={{ domain, sort, min: String(minScore) }} />

      {/* List */}
      {opportunities.length === 0 ? (
        <EmptyState
          icon={<Telescope size={32} />}
          title="No opportunities found"
          description="Run a discovery scan to detect research gaps, or lower the minimum score filter."
        />
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "1px", background: "var(--color-border)", border: "1px solid var(--color-border)" }}>
          {opportunities.map((opp, i) => (
            <Link key={opp.id} href={`/discover/${opp.id}`} style={{ textDecoration: "none" }}>
              <div
                style={{
                  background: "var(--color-surface)",
                  padding: "16px 18px",
                  display: "grid",
                  gridTemplateColumns: "48px 1fr auto",
                  gap: "16px",
                  alignItems: "start",
                  transition: "background 0.1s",
                }}
              >
                {/* Rank */}
                <div style={{ paddingTop: "2px" }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--color-text-muted)" }}>
                    #{String(i + 1).padStart(2, "0")}
                  </span>
                  <div
                    style={{
                      marginTop: "6px",
                      fontFamily: "var(--font-mono)",
                      fontSize: "20px",
                      fontWeight: 500,
                      color: scoreColor(opp.opportunity_score),
                      lineHeight: 1,
                    }}
                  >
                    {Math.round(opp.opportunity_score * 100)}
                  </div>
                  <div style={{ fontSize: "10px", color: "var(--color-text-muted)", marginTop: "2px" }}>score</div>
                </div>

                {/* Main content */}
                <div>
                  <h3 style={{ margin: "0 0 6px", fontSize: "14px", fontWeight: 600, color: "var(--color-text-primary)", lineHeight: 1.3 }}>
                    {opp.title}
                  </h3>
                  <p style={{ margin: "0 0 10px", fontSize: "12px", color: "var(--color-text-secondary)", lineHeight: 1.5, display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                    {opp.description || opp.hypothesis || "No description available."}
                  </p>

                  {/* Domain tags */}
                  <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", marginBottom: "10px" }}>
                    <Badge variant="indigo">{opp.domain_a}</Badge>
                    <span style={{ color: "var(--color-text-muted)", fontSize: "11px", alignSelf: "center" }}>×</span>
                    <Badge variant="amber">{opp.domain_b}</Badge>
                    {opp.bridge_concepts?.slice(0, 2).map((c) => (
                      <Badge key={c} variant="muted">{c}</Badge>
                    ))}
                  </div>

                  {/* Sub-scores */}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "8px" }}>
                    {[
                      { label: "Novelty",     val: opp.novelty_score },
                      { label: "Impact",      val: opp.impact_score },
                      { label: "Feasibility", val: opp.feasibility_score },
                      { label: "Velocity",    val: opp.velocity_score },
                    ].map(({ label, val }) => (
                      <div key={label}>
                        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "3px" }}>
                          <span style={{ fontSize: "10px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</span>
                          <span style={{ fontFamily: "var(--font-mono)", fontSize: "10px", color: "var(--color-text-secondary)" }}>{Math.round((val ?? 0) * 100)}</span>
                        </div>
                        <div style={{ height: "2px", background: "var(--color-border-2)", position: "relative" }}>
                          <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: `${(val ?? 0) * 100}%`, background: "var(--color-indigo)", opacity: 0.7 }} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Right action */}
                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "8px", paddingTop: "2px" }}>
                  <ArrowRight size={14} style={{ color: "var(--color-text-muted)" }} />
                  <span style={{ fontSize: "11px", color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>
                    {timeAgo(opp.generated_at)}
                  </span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function FilterBar({ current }: { current: { domain?: string; sort: string; min: string } }) {
  const sorts = [
    { val: "opportunity_score", label: "Score" },
    { val: "novelty_score",     label: "Novelty" },
    { val: "impact_score",      label: "Impact" },
  ];

  return (
    <div
      style={{
        display: "flex",
        gap: "8px",
        marginBottom: "16px",
        alignItems: "center",
        flexWrap: "wrap",
      }}
    >
      <span style={{ fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Sort:</span>
      {sorts.map(({ val, label }) => (
        <a
          key={val}
          href={`/discover?sort=${val}&min=${current.min}${current.domain ? `&domain=${current.domain}` : ""}`}
          style={{
            textDecoration: "none",
            padding: "4px 10px",
            fontSize: "12px",
            fontFamily: "var(--font-mono)",
            border: "1px solid",
            borderColor: current.sort === val ? "var(--color-indigo)" : "var(--color-border)",
            color: current.sort === val ? "var(--color-indigo)" : "var(--color-text-muted)",
            background: current.sort === val ? "rgba(99,102,241,0.08)" : "transparent",
          }}
        >
          {label}
        </a>
      ))}

      <span style={{ fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em", marginLeft: "8px" }}>Min:</span>
      {["0.4", "0.5", "0.6", "0.7"].map((m) => (
        <a
          key={m}
          href={`/discover?sort=${current.sort}&min=${m}${current.domain ? `&domain=${current.domain}` : ""}`}
          style={{
            textDecoration: "none",
            padding: "4px 10px",
            fontSize: "12px",
            fontFamily: "var(--font-mono)",
            border: "1px solid",
            borderColor: current.min === m ? "var(--color-amber)" : "var(--color-border)",
            color: current.min === m ? "var(--color-amber)" : "var(--color-text-muted)",
            background: current.min === m ? "rgba(245,158,11,0.08)" : "transparent",
          }}
        >
          {m}
        </a>
      ))}
    </div>
  );
}
