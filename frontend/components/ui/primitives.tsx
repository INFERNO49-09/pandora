"use client";

import { cn, formatNumber, formatScore, scoreColor, scoreLabel } from "@/lib/utils";

/* ── STAT CARD ────────────────────────────────────────────────────────── */
interface StatCardProps {
  label: string;
  value: number | string;
  sub?: string;
  accent?: "indigo" | "amber" | "green";
  mono?: boolean;
}

export function StatCard({ label, value, sub, accent = "indigo", mono = true }: StatCardProps) {
  const accentColors = {
    indigo: "var(--color-indigo)",
    amber:  "var(--color-amber)",
    green:  "var(--color-green)",
  };

  return (
    <div
      style={{
        background: "var(--color-surface)",
        border: "1px solid var(--color-border)",
        padding: "16px",
      }}
    >
      <p style={{ color: "var(--color-text-muted)", fontSize: "11px", letterSpacing: "0.08em", textTransform: "uppercase", margin: 0 }}>
        {label}
      </p>
      <p
        style={{
          fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)",
          fontSize: "28px",
          fontWeight: 500,
          color: accentColors[accent],
          margin: "4px 0 0",
          lineHeight: 1,
        }}
      >
        {typeof value === "number" ? formatNumber(value) : value}
      </p>
      {sub && (
        <p style={{ color: "var(--color-text-muted)", fontSize: "11px", margin: "4px 0 0" }}>{sub}</p>
      )}
    </div>
  );
}

/* ── SCORE BAR ────────────────────────────────────────────────────────── */
interface ScoreBarProps {
  score: number;
  label?: string;
  showValue?: boolean;
  height?: number;
}

export function ScoreBar({ score, label, showValue = true, height = 2 }: ScoreBarProps) {
  const color = scoreColor(score);
  return (
    <div>
      {(label || showValue) && (
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px" }}>
          {label && (
            <span style={{ fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
              {label}
            </span>
          )}
          {showValue && (
            <span style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color }}>
              {formatScore(score)}
            </span>
          )}
        </div>
      )}
      <div style={{ height: `${height}px`, background: "var(--color-border-2)", position: "relative", overflow: "hidden" }}>
        <div
          style={{
            position: "absolute",
            left: 0, top: 0, bottom: 0,
            width: `${score * 100}%`,
            background: `linear-gradient(90deg, var(--color-indigo), ${color})`,
            transition: "width 0.6s ease",
          }}
        />
      </div>
    </div>
  );
}

/* ── BADGE ────────────────────────────────────────────────────────────── */
interface BadgeProps {
  children: React.ReactNode;
  variant?: "indigo" | "amber" | "green" | "muted";
}

export function Badge({ children, variant = "muted" }: BadgeProps) {
  const styles = {
    indigo: { background: "rgba(99,102,241,0.12)",  color: "var(--color-indigo)", border: "1px solid rgba(99,102,241,0.25)" },
    amber:  { background: "rgba(245,158,11,0.12)",  color: "var(--color-amber)",  border: "1px solid rgba(245,158,11,0.25)" },
    green:  { background: "rgba(16,185,129,0.12)",  color: "var(--color-green)",  border: "1px solid rgba(16,185,129,0.25)" },
    muted:  { background: "var(--color-surface-2)", color: "var(--color-text-secondary)", border: "1px solid var(--color-border)" },
  };
  return (
    <span
      style={{
        ...styles[variant],
        display: "inline-block",
        padding: "2px 8px",
        fontSize: "11px",
        fontFamily: "var(--font-mono)",
        letterSpacing: "0.04em",
        borderRadius: "2px",
      }}
    >
      {children}
    </span>
  );
}

/* ── EMPTY STATE ──────────────────────────────────────────────────────── */
interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description?: string;
  action?: React.ReactNode;
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "64px 24px",
        gap: "12px",
        textAlign: "center",
      }}
    >
      {icon && (
        <div style={{ color: "var(--color-text-muted)", marginBottom: "4px" }}>{icon}</div>
      )}
      <p style={{ color: "var(--color-text-primary)", fontWeight: 500, margin: 0 }}>{title}</p>
      {description && (
        <p style={{ color: "var(--color-text-muted)", fontSize: "13px", maxWidth: "320px", margin: 0 }}>
          {description}
        </p>
      )}
      {action}
    </div>
  );
}

/* ── LOADING SKELETON ─────────────────────────────────────────────────── */
export function Skeleton({ width = "100%", height = 16 }: { width?: string | number; height?: number }) {
  return (
    <div
      style={{
        width,
        height,
        background: "var(--color-surface-2)",
        borderRadius: "2px",
        animation: "pulse 1.5s ease-in-out infinite",
      }}
    />
  );
}

/* ── SECTION HEADER ───────────────────────────────────────────────────── */
export function SectionHeader({
  title,
  sub,
  action,
}: {
  title: string;
  sub?: string;
  action?: React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: "16px" }}>
      <div>
        <h2 style={{ margin: 0, fontSize: "13px", fontWeight: 600, color: "var(--color-text-primary)", letterSpacing: "0.02em" }}>
          {title}
        </h2>
        {sub && (
          <p style={{ margin: "2px 0 0", fontSize: "12px", color: "var(--color-text-muted)" }}>{sub}</p>
        )}
      </div>
      {action}
    </div>
  );
}

/* ── DIVIDER ──────────────────────────────────────────────────────────── */
export function Divider() {
  return <div style={{ height: "1px", background: "var(--color-border)", margin: "0 -16px" }} />;
}
