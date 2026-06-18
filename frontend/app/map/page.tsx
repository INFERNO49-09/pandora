"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { api, type DomainNode, type DomainEdge, type GapOverlay } from "@/lib/api";
import { Badge } from "@/components/ui/primitives";
import { scoreColor, nodeTypeColor } from "@/lib/utils";
import { Search, ZoomIn, ZoomOut, Maximize2, Info } from "lucide-react";

interface MapData {
  nodes: DomainNode[];
  edges: DomainEdge[];
  gap_overlays: GapOverlay[];
}

export default function ScienceMapPage() {
  const cyRef        = useRef<HTMLDivElement>(null);
  const cyInstance   = useRef<any>(null);
  const [loading, setLoading]     = useState(true);
  const [mapData, setMapData]     = useState<MapData | null>(null);
  const [selected, setSelected]   = useState<any>(null);
  const [search, setSearch]       = useState("");
  const [showGaps, setShowGaps]   = useState(true);
  const [nodeCount, setNodeCount] = useState(0);
  const [edgeCount, setEdgeCount] = useState(0);

  // Load domain map data
  useEffect(() => {
    api.discovery.domainMap().then(setMapData).catch(console.error).finally(() => setLoading(false));
  }, []);

  // Initialize Cytoscape when data arrives
  useEffect(() => {
    if (!mapData || !cyRef.current) return;

    let cy: any;
    // Dynamic import — cytoscape uses browser APIs
    import("cytoscape").then(async (cytoscapeModule) => {
      const cytoscape = cytoscapeModule.default;

      // Build elements
      const gapSet = new Set(
        mapData.gap_overlays.map((g) => `${g.domain_a}||${g.domain_b}`)
      );

      const domainNameToId = new Map(mapData.nodes.map((n) => [n.name, n.id]));

      const elements: any[] = [
        ...mapData.nodes.map((n) => ({
          data: {
            id: n.id,
            label: n.name,
            paper_count: n.paper_count,
            size: Math.max(20, Math.min(60, Math.sqrt(n.paper_count ?? 1) * 3)),
            type: "Domain",
          },
        })),
        ...mapData.edges.map((e, i) => {
          const key1 = `${e.source_name}||${e.target_name}`;
          const key2 = `${e.target_name}||${e.source_name}`;
          const isGap = gapSet.has(key1) || gapSet.has(key2);
          return {
            data: {
              id: `e-${i}`,
              source: e.source,
              target: e.target,
              bridge_papers: e.bridge_papers,
              isGap,
              weight: Math.max(1, Math.min(8, Math.log1p(e.bridge_papers))),
            },
          };
        }),
      ];

      cy = cytoscape({
        container: cyRef.current,
        elements,
        style: [
          {
            selector: "node",
            style: {
              "background-color": "#6366F1",
              "background-opacity": 0.85,
              label: "data(label)",
              color: "#F8FAFC",
              "font-size": "10px",
              "font-family": "Inter, sans-serif",
              "text-valign": "center",
              "text-halign": "center",
              "text-wrap": "ellipsis",
              "text-max-width": "80px",
              width: "data(size)",
              height: "data(size)",
              "border-width": 1,
              "border-color": "#2A2F42",
            },
          },
          {
            selector: "node:selected",
            style: {
              "background-color": "#F59E0B",
              "border-color": "#F59E0B",
              "border-width": 2,
            },
          },
          {
            selector: "edge",
            style: {
              width: "data(weight)",
              "line-color": "#1E2230",
              "curve-style": "bezier",
              opacity: 0.6,
            },
          },
          {
            selector: "edge[?isGap]",
            style: {
              "line-color": "#6366F1",
              opacity: 0.9,
              "line-style": "dashed",
              "line-dash-pattern": [6, 4],
              width: 1.5,
            },
          },
        ],
        layout: {
          name: "cose",
          animate: false,
          nodeRepulsion: () => 8000,
          idealEdgeLength: () => 100,
          nodeOverlap: 20,
          fit: true,
          padding: 40,
        },
      });

      cyInstance.current = cy;
      setNodeCount(cy.nodes().length);
      setEdgeCount(cy.edges().length);

      // Click handler
      cy.on("tap", "node", (evt: any) => {
        const node = evt.target;
        setSelected({
          id: node.id(),
          label: node.data("label"),
          paper_count: node.data("paper_count"),
          type: "Domain",
          neighbors: node.neighborhood("node").map((n: any) => n.data("label")),
        });
      });

      cy.on("tap", (evt: any) => {
        if (evt.target === cy) setSelected(null);
      });
    });

    return () => {
      cy?.destroy();
    };
  }, [mapData]);

  // Search — highlight matching nodes
  useEffect(() => {
    const cy = cyInstance.current;
    if (!cy || !search) {
      cy?.nodes().removeStyle("border-color border-width opacity");
      return;
    }
    const q = search.toLowerCase();
    cy.nodes().forEach((n: any) => {
      if (n.data("label").toLowerCase().includes(q)) {
        n.style({ "border-color": "#F59E0B", "border-width": 3, opacity: 1 });
      } else {
        n.style({ opacity: 0.2 });
      }
    });
  }, [search]);

  // Gap overlay toggle
  useEffect(() => {
    const cy = cyInstance.current;
    if (!cy) return;
    cy.edges("[?isGap]").style({ display: showGaps ? "element" : "none" });
  }, [showGaps]);

  const zoom = useCallback((dir: "in" | "out") => {
    const cy = cyInstance.current;
    if (!cy) return;
    cy.zoom({ level: cy.zoom() * (dir === "in" ? 1.3 : 0.75), renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  }, []);

  const fit = useCallback(() => { cyInstance.current?.fit(undefined, 40); }, []);

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column" }}>

      {/* Toolbar */}
      <div
        style={{
          padding: "10px 16px",
          background: "var(--color-surface)",
          borderBottom: "1px solid var(--color-border)",
          display: "flex",
          gap: "12px",
          alignItems: "center",
          flexShrink: 0,
        }}
      >
        <p style={{ margin: 0, fontSize: "11px", fontFamily: "var(--font-mono)", color: "var(--color-indigo)", letterSpacing: "0.08em" }}>
          PANDORA / SCIENCE MAP
        </p>

        {/* Search */}
        <div style={{ display: "flex", alignItems: "center", gap: "6px", background: "var(--color-bg)", border: "1px solid var(--color-border)", padding: "4px 10px", flex: "0 0 220px" }}>
          <Search size={12} style={{ color: "var(--color-text-muted)" }} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search domains..."
            style={{ background: "none", border: "none", outline: "none", color: "var(--color-text-primary)", fontSize: "12px", fontFamily: "var(--font-mono)", width: "100%" }}
          />
        </div>

        {/* Gap toggle */}
        <button
          onClick={() => setShowGaps((v) => !v)}
          style={{
            background: showGaps ? "rgba(99,102,241,0.12)" : "transparent",
            border: "1px solid",
            borderColor: showGaps ? "var(--color-indigo)" : "var(--color-border)",
            color: showGaps ? "var(--color-indigo)" : "var(--color-text-muted)",
            fontSize: "11px",
            fontFamily: "var(--font-mono)",
            padding: "4px 10px",
            cursor: "pointer",
            letterSpacing: "0.04em",
          }}
        >
          {showGaps ? "GAPS ON" : "GAPS OFF"}
        </button>

        {/* Zoom controls */}
        <div style={{ display: "flex", gap: "4px", marginLeft: "auto" }}>
          {[
            { icon: <ZoomIn size={14} />,    fn: () => zoom("in"),  title: "Zoom in" },
            { icon: <ZoomOut size={14} />,   fn: () => zoom("out"), title: "Zoom out" },
            { icon: <Maximize2 size={14} />, fn: fit,               title: "Fit" },
          ].map(({ icon, fn, title }, i) => (
            <button
              key={i}
              onClick={fn}
              title={title}
              style={{
                background: "var(--color-bg)",
                border: "1px solid var(--color-border)",
                color: "var(--color-text-muted)",
                width: "28px", height: "28px",
                display: "flex", alignItems: "center", justifyContent: "center",
                cursor: "pointer",
              }}
            >
              {icon}
            </button>
          ))}
        </div>

        {/* Stats */}
        <div style={{ display: "flex", gap: "12px" }}>
          {[{ label: "nodes", val: nodeCount }, { label: "edges", val: edgeCount }].map(({ label, val }) => (
            <span key={label} style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--color-text-muted)" }}>
              <span style={{ color: "var(--color-text-primary)" }}>{val}</span> {label}
            </span>
          ))}
        </div>
      </div>

      {/* Graph + panel */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>

        {/* Cytoscape canvas */}
        <div style={{ flex: 1, position: "relative" }}>
          {loading && (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", zIndex: 10 }}>
              <div style={{ textAlign: "center" }}>
                <div style={{ width: "32px", height: "32px", border: "2px solid var(--color-border)", borderTopColor: "var(--color-indigo)", borderRadius: "50%", animation: "spin 0.8s linear infinite", margin: "0 auto 12px" }} />
                <p style={{ color: "var(--color-text-muted)", fontSize: "12px", margin: 0 }}>Loading graph...</p>
              </div>
            </div>
          )}
          <div ref={cyRef} style={{ width: "100%", height: "100%", background: "var(--color-bg)" }} />

          {/* Legend */}
          <div
            style={{
              position: "absolute",
              bottom: "16px",
              left: "16px",
              background: "var(--color-surface)",
              border: "1px solid var(--color-border)",
              padding: "10px 12px",
              fontSize: "11px",
            }}
          >
            <p style={{ margin: "0 0 6px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Legend</p>
            {[
              { color: "#6366F1", label: "Domain node" },
              { color: "#1E2230", label: "Connection (existing)" },
              { color: "#6366F1", label: "Gap (predicted opportunity)", dashed: true },
            ].map(({ color, label, dashed }) => (
              <div key={label} style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "3px" }}>
                <div style={{
                  width: "20px", height: "2px", background: color,
                  ...(dashed ? { backgroundImage: `repeating-linear-gradient(90deg, ${color} 0, ${color} 4px, transparent 4px, transparent 8px)`, background: "none" } : {}),
                }} />
                <span style={{ color: "var(--color-text-muted)" }}>{label}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Side panel — selected node */}
        {selected && (
          <div
            style={{
              width: "280px",
              borderLeft: "1px solid var(--color-border)",
              background: "var(--color-surface)",
              padding: "16px",
              overflowY: "auto",
              animation: "slide-in-left 0.15s ease",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "16px" }}>
              <div>
                <Badge variant="indigo">Domain</Badge>
                <h3 style={{ margin: "6px 0 0", fontSize: "15px", fontWeight: 600 }}>{selected.label}</h3>
              </div>
              <button onClick={() => setSelected(null)} style={{ background: "none", border: "none", color: "var(--color-text-muted)", cursor: "pointer", padding: "2px" }}>✕</button>
            </div>

            <div style={{ marginBottom: "16px" }}>
              <p style={{ margin: "0 0 2px", fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>Papers</p>
              <p style={{ margin: 0, fontFamily: "var(--font-mono)", fontSize: "20px", color: "var(--color-indigo)" }}>
                {(selected.paper_count ?? 0).toLocaleString()}
              </p>
            </div>

            {selected.neighbors?.length > 0 && (
              <div>
                <p style={{ margin: "0 0 8px", fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                  Connected Domains ({selected.neighbors.length})
                </p>
                <div style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                  {selected.neighbors.slice(0, 10).map((n: string) => (
                    <div key={n} style={{ fontSize: "12px", color: "var(--color-text-secondary)", padding: "3px 0", borderBottom: "1px solid var(--color-border)" }}>
                      {n}
                    </div>
                  ))}
                  {selected.neighbors.length > 10 && (
                    <p style={{ fontSize: "11px", color: "var(--color-text-muted)", margin: "4px 0 0" }}>
                      +{selected.neighbors.length - 10} more
                    </p>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes slide-in-left {
          from { opacity: 0; transform: translateX(12px); }
          to   { opacity: 1; transform: translateX(0); }
        }
      `}</style>
    </div>
  );
}
