import { api } from "@/lib/api";
import { StatCard, SectionHeader, Badge } from "@/components/ui/primitives";
import { formatNumber, scoreColor } from "@/lib/utils";
import Link from "next/link";
import { ArrowRight, Telescope, TrendingUp, Zap } from "lucide-react";

async function getStats() {
  try { return await api.discovery.stats(); } catch { return null; }
}
async function getTopOpportunities() {
  try {
    const res = await api.discovery.opportunities({ limit: 5, min_score: 0.5 });
    return res.opportunities;
  } catch { return []; }
}
async function getIngestStatus() {
  try { return await api.ingest.status(); } catch { return null; }
}

export default async function OverviewPage() {
  const [stats, opportunities, ingest] = await Promise.all([
    getStats(),
    getTopOpportunities(),
    getIngestStatus(),
  ]);

  return (
    <div style={{ padding: "32px", maxWidth: "1100px" }}>
      <div style={{ marginBottom: "32px" }}>
        <p style={{ color: "var(--color-indigo)", fontFamily: "var(--font-mono)", fontSize: "11px", letterSpacing: "0.1em", textTransform: "uppercase", margin: "0 0 8px" }}>
          PANDORA / OVERVIEW
        </p>
        <h1 style={{ fontSize: "24px", fontWeight: 600, margin: "0 0 4px", color: "var(--color-text-primary)" }}>
          Scientific Discovery Engine
        </h1>
        <p style={{ color: "var(--color-text-secondary)", margin: 0 }}>
          Find the connections science has not made yet.
        </p>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "1px", background: "var(--color-border)", marginBottom: "32px", border: "1px solid var(--color-border)" }}>
        <StatCard label="Papers" value={stats?.papers ?? 0} accent="indigo" />
        <StatCard label="Concepts" value={stats?.concepts ?? 0} accent="indigo" />
        <StatCard label="Relationships" value={stats?.total_relationships ?? 0} accent="amber" />
        <StatCard label="Opportunities" value={stats?.opportunities ?? 0} accent="green" />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px" }}>
        <div>
          <SectionHeader
            title="Top Opportunities"
            sub="Highest-scoring research gaps"
            action={
              <Link href="/discover" style={{ color: "var(--color-indigo)", fontSize: "12px", display: "flex", alignItems: "center", gap: "4px", textDecoration: "none" }}>
                All <ArrowRight size={12} />
              </Link>
            }
          />
          <div style={{ display: "flex", flexDirection: "column", gap: "1px" }}>
            {opportunities.length === 0 ? (
              <div style={{ padding: "24px", background: "var(--color-surface)", border: "1px solid var(--color-border)", color: "var(--color-text-muted)", fontSize: "13px" }}>
                No opportunities yet. Run <code style={{ fontFamily: "var(--font-mono)", color: "var(--color-indigo)" }}>make scan</code> to discover them.
              </div>
            ) : opportunities.map((opp) => (
              <Link key={opp.id} href={`/discover/${opp.id}`} style={{ textDecoration: "none", display: "block" }}>
                <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", padding: "12px 14px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: "8px" }}>
                    <p style={{ margin: 0, fontSize: "13px", color: "var(--color-text-primary)", fontWeight: 500, lineHeight: 1.3 }}>
                      {opp.title}
                    </p>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: "13px", fontWeight: 500, color: scoreColor(opp.opportunity_score), flexShrink: 0 }}>
                      {Math.round(opp.opportunity_score * 100)}
                    </span>
                  </div>
                  <div style={{ display: "flex", gap: "6px", marginTop: "6px" }}>
                    <Badge variant="indigo">{opp.domain_a}</Badge>
                    <span style={{ color: "var(--color-text-muted)", fontSize: "11px", alignSelf: "center" }}>x</span>
                    <Badge variant="amber">{opp.domain_b}</Badge>
                  </div>
                </div>
              </Link>
            ))}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          <div>
            <SectionHeader title="Explore" />
            <div style={{ display: "flex", flexDirection: "column", gap: "1px" }}>
              {[
                { href: "/map",     icon: <Telescope size={15} />,  label: "Science Map",     desc: "Visualize domain connections" },
                { href: "/trends",  icon: <TrendingUp size={15} />, label: "Trend Analysis",  desc: "Fastest-growing research areas" },
                { href: "/predict", icon: <Zap size={15} />,        label: "Link Prediction", desc: "Find missing concept links" },
              ].map(({ href, icon, label, desc }) => (
                <Link key={href} href={href} style={{ textDecoration: "none" }}>
                  <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", padding: "12px 14px", display: "flex", gap: "12px", alignItems: "center" }}>
                    <span style={{ color: "var(--color-indigo)" }}>{icon}</span>
                    <div>
                      <p style={{ margin: 0, fontSize: "13px", fontWeight: 500, color: "var(--color-text-primary)" }}>{label}</p>
                      <p style={{ margin: 0, fontSize: "12px", color: "var(--color-text-muted)" }}>{desc}</p>
                    </div>
                    <ArrowRight size={14} style={{ marginLeft: "auto", color: "var(--color-text-muted)" }} />
                  </div>
                </Link>
              ))}
            </div>
          </div>

          <div>
            <SectionHeader title="Graph Status" />
            <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", padding: "14px", display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
              {[
                { label: "Domains", value: stats?.domains ?? 0 },
                { label: "Methods", value: stats?.methods ?? 0 },
                { label: "Authors", value: stats?.authors ?? 0 },
                { label: "Latest year", value: ingest?.most_recent_year ?? "—", mono: false },
              ].map(({ label, value, mono = true }) => (
                <div key={label}>
                  <p style={{ margin: 0, fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</p>
                  <p style={{ margin: "2px 0 0", fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)", fontSize: "18px", color: "var(--color-text-primary)" }}>
                    {typeof value === "number" ? formatNumber(value) : value}
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
