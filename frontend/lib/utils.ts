import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatScore(score: number): string {
  return (score * 100).toFixed(0);
}

export function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

export function scoreColor(score: number): string {
  if (score >= 0.75) return "#F59E0B"; // amber — high opportunity
  if (score >= 0.55) return "#6366F1"; // indigo — medium
  return "#475569";                    // muted — low
}

export function scoreLabel(score: number): string {
  if (score >= 0.75) return "High";
  if (score >= 0.55) return "Medium";
  return "Low";
}

export function timeAgo(dateStr: string): string {
  const d = new Date(dateStr);
  const now = Date.now();
  const diff = now - d.getTime();
  const hours = Math.floor(diff / 3_600_000);
  if (hours < 1) return "just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return d.toLocaleDateString();
}

export function nodeTypeColor(type: string): string {
  const colors: Record<string, string> = {
    Paper:               "#6366F1",
    Concept:             "#10B981",
    Domain:              "#F59E0B",
    Method:              "#3B82F6",
    Author:              "#8B5CF6",
    ResearchOpportunity: "#EF4444",
    Dataset:             "#EC4899",
  };
  return colors[type] ?? "#94A3B8";
}
