from datetime import datetime
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


# ── ENUMS ─────────────────────────────────────────────────────────────────────

class IngestionStatus(str, Enum):
    QUEUED = "queued"
    FETCHING = "fetching"
    EXTRACTING = "extracting"
    RESOLVING = "resolving"
    EMBEDDING = "embedding"
    GRAPH_WRITE = "graph_write"
    COMPLETE = "complete"
    FAILED = "failed"
    DUPLICATE = "duplicate"


class NodeType(str, Enum):
    PAPER = "Paper"
    CONCEPT = "Concept"
    AUTHOR = "Author"
    INSTITUTION = "Institution"
    METHOD = "Method"
    DATASET = "Dataset"
    DOMAIN = "Domain"
    METRIC = "Metric"
    OPPORTUNITY = "ResearchOpportunity"
    PROBLEM = "ResearchProblem"


class RelationType(str, Enum):
    CITES = "CITES"
    USES = "USES"
    EXTENDS = "EXTENDS"
    IMPROVES = "IMPROVES"
    INTRODUCES = "INTRODUCES"
    IN_DOMAIN = "IN_DOMAIN"
    RELATED_TO = "RELATED_TO"
    APPLIED_IN = "APPLIED_IN"
    AUTHORED_BY = "AUTHORED_BY"
    AFFILIATED_WITH = "AFFILIATED_WITH"
    ADDRESSES = "ADDRESSES"
    CONTRADICTS = "CONTRADICTS"
    BRIDGES = "BRIDGES"
    SUPPORTED_BY = "SUPPORTED_BY"


class OpportunityStatus(str, Enum):
    ACTIVE = "active"
    VALIDATED = "validated"
    DISMISSED = "dismissed"
    IN_PROGRESS = "in_progress"


# ── RAW PAPER (from ingestion source) ─────────────────────────────────────────

class RawPaper(BaseModel):
    source: str                         # "arxiv", "openalex", "pubmed"
    source_id: str                      # ID within that source
    doi: str | None = None
    arxiv_id: str | None = None
    title: str
    abstract: str
    authors: list[str] = []
    year: int | None = None
    venue: str | None = None
    citation_count: int = 0
    references: list[str] = []          # DOIs or source IDs of cited papers
    keywords: list[str] = []
    url: str | None = None
    pdf_url: str | None = None


# ── EXTRACTION RESULT ─────────────────────────────────────────────────────────

class ExtractedConcept(BaseModel):
    name: str
    canonical_name: str | None = None   # resolved after entity resolution
    domain: str | None = None
    confidence: float = 1.0
    source_text: str | None = None      # provenance: where in the paper


class ExtractedMethod(BaseModel):
    name: str
    canonical_name: str | None = None
    category: str | None = None         # architecture, algorithm, training, evaluation
    confidence: float = 1.0


class ExtractedRelation(BaseModel):
    head: str                           # entity name
    head_type: str
    relation: str                       # e.g. "USES", "IMPROVES"
    tail: str
    tail_type: str
    confidence: float = 1.0
    source_text: str | None = None


class ExtractedProblem(BaseModel):
    description: str
    problem_type: str                   # limitation, open_problem, future_work
    severity: str = "minor"            # major, minor
    domain: str | None = None


class ExtractionResult(BaseModel):
    paper_id: str
    concepts: list[ExtractedConcept] = []
    methods: list[ExtractedMethod] = []
    relations: list[ExtractedRelation] = []
    open_problems: list[ExtractedProblem] = []
    domains: list[str] = []
    error: str | None = None


# ── GRAPH NODES ───────────────────────────────────────────────────────────────

class PaperNode(BaseModel):
    id: str
    title: str
    abstract: str | None = None
    year: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    venue: str | None = None
    citation_count: int = 0
    source: str | None = None
    pagerank_score: float = 0.0


class ConceptNode(BaseModel):
    id: str
    canonical_name: str
    domain: str | None = None
    paper_count: int = 0
    growth_rate: float = 0.0            # papers/year trend
    embedding_id: str | None = None


class DomainNode(BaseModel):
    id: str
    name: str
    paper_count: int = 0
    growth_rate: float = 0.0
    pagerank_score: float = 0.0


# ── DISCOVERY TYPES ───────────────────────────────────────────────────────────

class GapScore(BaseModel):
    opportunity_score: float            # composite 0-1
    novelty_score: float = 0.0
    impact_score: float = 0.0
    feasibility_score: float = 0.0
    velocity_score: float = 0.0
    embedding_proximity: float = 0.0
    evidence: dict[str, Any] = {}


class LinkPrediction(BaseModel):
    source_node_id: str
    source_node_type: str
    source_name: str
    target_node_id: str
    target_node_type: str
    target_name: str
    predicted_relation: str
    confidence: float
    model_name: str
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class ResearchOpportunity(BaseModel):
    id: str
    title: str
    description: str
    domain_a: str
    domain_b: str
    bridge_concepts: list[str] = []
    opportunity_score: float
    novelty_score: float = 0.0
    impact_score: float = 0.0
    feasibility_score: float = 0.0
    velocity_score: float = 0.0
    hypothesis: str | None = None
    hypothesis_rationale: str | None = None
    experimental_approach: str | None = None
    supporting_paper_ids: list[str] = []
    status: OpportunityStatus = OpportunityStatus.ACTIVE
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    score_evidence: dict[str, Any] = {}


class ContradictionReport(BaseModel):
    id: str
    paper_a_id: str
    paper_a_title: str
    paper_b_id: str
    paper_b_title: str
    dataset: str | None = None
    metric: str | None = None
    paper_a_value: float | None = None
    paper_b_value: float | None = None
    confidence: float
    explanation: str
    contradiction_type: str
    detected_at: datetime = Field(default_factory=datetime.utcnow)


class TrendPrediction(BaseModel):
    entity_id: str
    entity_name: str
    entity_type: str
    growth_probability: float
    key_drivers: list[str] = []
    historical_paper_counts: list[dict] = []  # [{year, count}]
    forecast_year: int


# ── API RESPONSE TYPES ────────────────────────────────────────────────────────

class IngestionJobResponse(BaseModel):
    job_id: str
    status: IngestionStatus
    message: str | None = None


class GraphSubgraph(BaseModel):
    nodes: list[dict]
    edges: list[dict]
    node_count: int
    edge_count: int


class DiscoveryStats(BaseModel):
    total_papers: int
    total_concepts: int
    total_domains: int
    total_relationships: int
    total_opportunities: int
    last_discovery_run: datetime | None = None
    graph_coverage_domains: list[str] = []
