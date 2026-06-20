"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Telescope,
  Map,
  TrendingUp,
  GitBranch,
  Upload,
  Activity,
  Zap,
  AlertTriangle,
  MessageSquare,
  Cpu,
  Bookmark,
  History,
  Settings,
} from "lucide-react";

const NAV = [
  { href: "/",               icon: Activity,       label: "Overview"        },
  { href: "/discover",       icon: Telescope,      label: "Opportunities"   },
  { href: "/map",            icon: Map,            label: "Science Map"     },
  { href: "/trends",         icon: TrendingUp,     label: "Trends"          },
  { href: "/predict",        icon: Zap,            label: "Predict"         },
  { href: "/contradictions", icon: AlertTriangle,  label: "Contradictions"  },
  { href: "/copilot",        icon: MessageSquare,  label: "Copilot"         },
  { href: "/bookmarks",      icon: Bookmark,       label: "Bookmarks"       },
  { href: "/models",         icon: Cpu,            label: "Models"          },
  { href: "/ingest",         icon: Upload,         label: "Ingest"          },
  { href: "/settings",       icon: Settings,       label: "Settings"        },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside
      style={{
        width: "var(--sidebar-width)",
        minWidth: "var(--sidebar-width)",
        background: "var(--color-surface)",
        borderRight: "1px solid var(--color-border)",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        paddingTop: "12px",
        paddingBottom: "12px",
        gap: "4px",
        zIndex: 50,
      }}
    >
      {/* Logo */}
      <div
        style={{
          width: "32px",
          height: "32px",
          borderRadius: "8px",
          background: "var(--color-indigo)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          marginBottom: "16px",
        }}
      >
        <GitBranch size={16} color="white" />
      </div>

      {/* Nav items */}
      {NAV.map(({ href, icon: Icon, label }) => {
        const active = pathname === href || (href !== "/" && pathname.startsWith(href));
        return (
          <Link
            key={href}
            href={href}
            title={label}
            style={{
              width: "40px",
              height: "40px",
              borderRadius: "8px",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: active ? "var(--color-indigo)" : "var(--color-text-muted)",
              background: active ? "rgba(99,102,241,0.12)" : "transparent",
              border: active ? "1px solid rgba(99,102,241,0.25)" : "1px solid transparent",
              transition: "all 0.15s ease",
              textDecoration: "none",
            }}
          >
            <Icon size={18} />
          </Link>
        );
      })}
    </aside>
  );
}
