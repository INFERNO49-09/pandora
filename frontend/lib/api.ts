/**
 * Pandora API client.
 * All data fetching goes through here — no raw fetch() elsewhere.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

async function get<T>(path: string, params?: Record<string, string | number | boolean>): Promise<T> {
  const url = new URL(`${BASE}${path}`);
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
    });
  }
  const res = await fetch(url.toString(), { next: { revalidate: 30 } });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`API POST ${path} → ${res.status}`);
  return res.json();
}

// ── DISCOVERY ──────────────────────────────────────────────────────────────

export interface Opportunity {
  id: string;
  title: string;
  description: string;
  domain_a: string;
  domain_b: string;
  bridge_concepts: string[];
  opportunity_score: number;
  novelty_score: number;
  impact_score: number;
  feasibility_score: number;
  velocity_score: number;
  hypothesis?: string;
  hypothesis_rationale?: string;
  experimental_approach?: string;
  status: string;
  generated_at: string;
}

export interface OpportunitiesResponse {
  opportunities: Opportunity[];
  total: number;
  offset: number;
  limit: number;
}

export interface DiscoveryStats {
  papers: number;
  concepts: number;
  domains: number;
  methods: number;
  authors: number;
  opportunities: number;
  total_relationships: number;
}

export interface DomainMapResponse {
  nodes: DomainNode[];
  edges: DomainEdge[];
  gap_overlays: GapOverlay[];
}

export interface DomainNode {
  id: string;
  name: string;
  paper_count: number;
  growth_rate?: number;
}

export interface DomainEdge {
  source: string;
  target: string;
  bridge_papers: number;
  source_name: string;
  target_name: string;
}

export interface GapOverlay {
  domain_a: string;
  domain_b: string;
  score: number;
  id: string;
}

export interface ScoreResponse {
  domain_a: string;
  domain_b: string;
  score: {
    opportunity_score: number;
    novelty_score: number;
    impact_score: number;
    feasibility_score: number;
    velocity_score: number;
    embedding_proximity: number;
  };
  hypothesis_generation: string;
}

// ── GRAPH ──────────────────────────────────────────────────────────────────

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  data: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  data: Record<string, unknown>;
}

export interface SubgraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  node_count: number;
  edge_count: number;
}

export interface SearchResult {
  id: string;
  label: string;
  type: string;
  score: number;
  data: Record<string, unknown>;
}

// ── TRENDS ────────────────────────────────────────────────────────────────

export interface TrendConcept {
  id: string;
  name: string;
  domain: string;
  recent_count: number;
  total_count: number;
  recency_ratio: number;
}

export interface TrendDomain {
  id: string;
  name: string;
  recent_papers: number;
  total_papers: number;
  growth_ratio: number;
}

export interface EmergingIntersection {
  domain_a: string;
  domain_b: string;
  recent_bridges: number;
  total_bridges: number;
  emergence_ratio: number;
}

// ── LINK PREDICTION ───────────────────────────────────────────────────────

export interface LinkPrediction {
  source_node_id: string;
  source_name: string;
  target_node_id: string;
  target_name: string;
  predicted_relation: string;
  confidence: number;
  model_name: string;
}

// ── API FUNCTIONS ─────────────────────────────────────────────────────────

export const api = {
  discovery: {
    stats: () => get<DiscoveryStats>("/discover/stats"),
    opportunities: (params?: {
      domain?: string;
      min_score?: number;
      sort_by?: string;
      limit?: number;
      offset?: number;
    }) => get<OpportunitiesResponse>("/discover/opportunities", params as Record<string, string | number | boolean>),
    opportunity: (id: string) => get<Opportunity & { supporting_papers: unknown[]; linked_domains: string[] }>(`/discover/opportunities/${id}`),
    domainMap: () => get<DomainMapResponse>("/discover/domain-map"),
    score: (domain_a_name: string, domain_b_name: string) =>
      post<ScoreResponse>("/discover/score", { domain_a_name, domain_b_name }),
  },
  graph: {
    subgraph: (seed_ids: string[], depth = 2, max_nodes = 300) =>
      post<SubgraphResponse>("/graph/subgraph", { seed_ids, depth, max_nodes }),
    search: (q: string) =>
      get<{ results: SearchResult[]; query: string }>("/graph/search", { q }),
    node: (id: string) => get<{ node: Record<string, unknown>; labels: string[]; relationships: unknown[] }>(`/graph/node/${id}`),
    domains: () => get<{ domains: DomainNode[] }>("/graph/domains"),
  },
  trends: {
    concepts: (limit = 20) => get<{ trends: TrendConcept[] }>("/trends/concepts", { limit }),
    domains: (limit = 20) => get<{ domains: TrendDomain[] }>("/trends/domains", { limit }),
    emerging: (limit = 10) => get<{ emerging_intersections: EmergingIntersection[] }>("/trends/emerging-intersections", { limit }),
    timeline: (domain: string, years = 10) =>
      get<{ domain: string; timeline: { year: number; papers: number }[] }>("/trends/publication-timeline", { domain, years }),
  },
  ingest: {
    seed: (topic: string, source: string, max_results: number) =>
      post<{ job_id: string; status: string; message: string }>("/ingest/seed", { topic, source, max_results }),
    jobStatus: (job_id: string) => get<{ job_id: string; status: string; result?: unknown }>(`/ingest/jobs/${job_id}`),
    status: () => get<{ papers_in_graph: number; papers_this_year: number; most_recent_year: number }>("/ingest/status"),
  },
  predict: {
    links: (node_id: string, node_type: string, top_k = 10) =>
      post<{ predictions: LinkPrediction[]; source_node: { name: string } }>("/predict/links", { node_id, node_type, top_k }),
    missingConnections: (domain: string) =>
      get<{ missing_connections: { source_name: string; target_name: string; similarity: number }[] }>("/predict/missing-connections", { domain }),
  },
};
