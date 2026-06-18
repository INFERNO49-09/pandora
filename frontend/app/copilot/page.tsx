"use client";

import { useState, useRef, useEffect } from "react";
import { Badge } from "@/components/ui/primitives";
import { Send, Telescope, Loader, BookOpen, Zap } from "lucide-react";
import Link from "next/link";

interface SSEEvent {
  type: "thinking" | "token" | "citation" | "opportunity" | "complete" | "error";
  content: string | Record<string, unknown>;
}

interface Message {
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  opportunities: Opportunity[];
  thinking: string[];
  complete: boolean;
}

interface Citation {
  paper_id: string;
  title: string;
  year?: number;
}

interface Opportunity {
  id: string;
  title: string;
  domain_a: string;
  domain_b: string;
  score: number;
}

const EXAMPLE_QUERIES = [
  "What are the most promising unexplored areas in medical AI?",
  "What missing relationships exist between federated learning and drug discovery?",
  "Which interdisciplinary fields are emerging fastest?",
  "What opportunities exist between graph neural networks and healthcare?",
];

export default function CopilotPage() {
  const [messages,  setMessages]  = useState<Message[]>([]);
  const [input,     setInput]     = useState("");
  const [streaming, setStreaming] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const threadId  = useRef(`thread-${Date.now()}`);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const sendQuery = async (query: string) => {
    if (!query.trim() || streaming) return;

    const userMsg: Message = {
      role: "user", content: query,
      citations: [], opportunities: [], thinking: [], complete: true,
    };
    const assistantMsg: Message = {
      role: "assistant", content: "",
      citations: [], opportunities: [], thinking: [], complete: false,
    };

    setMessages(prev => [...prev, userMsg, assistantMsg]);
    setInput("");
    setStreaming(true);

    try {
      const res = await fetch("/api/v1/copilot/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, thread_id: threadId.current }),
      });

      if (!res.body) throw new Error("No response body");

      const reader  = res.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split("\n").filter(l => l.startsWith("data: "));

        for (const line of lines) {
          try {
            const event: SSEEvent = JSON.parse(line.slice(6));

            setMessages(prev => {
              const updated = [...prev];
              const last    = { ...updated[updated.length - 1] };

              if (event.type === "token") {
                last.content += typeof event.content === "string" ? event.content : "";
              } else if (event.type === "thinking") {
                const msg = ((event.content as unknown) as Record<string, string>).message || "";
                if (msg && !last.thinking.includes(msg)) {
                  last.thinking = [...last.thinking, msg];
                }
              } else if (event.type === "citation") {
                const c = event.content as unknown as Citation;
                if (c.paper_id && !last.citations.find(x => x.paper_id === c.paper_id)) {
                  last.citations = [...last.citations, c];
                }
              } else if (event.type === "opportunity") {
                const o = event.content as unknown as Opportunity;
                if (o.id && !last.opportunities.find(x => x.id === o.id)) {
                  last.opportunities = [...last.opportunities, o];
                }
              } else if (event.type === "complete") {
                last.complete = true;
              }

              updated[updated.length - 1] = last;
              return updated;
            });
          } catch { /* ignore parse errors */ }
        }
      }
    } catch (e) {
      console.error(e);
      setMessages(prev => {
        const updated = [...prev];
        const last    = { ...updated[updated.length - 1] };
        last.content  = "An error occurred. Make sure the backend is running.";
        last.complete = true;
        updated[updated.length - 1] = last;
        return updated;
      });
    } finally {
      setStreaming(false);
    }
  };

  return (
    <div style={{ height: "100vh", display: "flex", flexDirection: "column" }}>

      {/* Top bar */}
      <div style={{ padding: "10px 24px", background: "var(--color-surface)", borderBottom: "1px solid var(--color-border)", display: "flex", alignItems: "center", gap: "12px", flexShrink: 0 }}>
        <Telescope size={16} style={{ color: "var(--color-indigo)" }} />
        <p style={{ margin: 0, fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--color-indigo)", letterSpacing: "0.08em" }}>
          PANDORA / DISCOVERY COPILOT
        </p>
        <p style={{ margin: "0 0 0 auto", fontSize: "11px", color: "var(--color-text-muted)" }}>
          Agent-powered · Cites sources · Reasons over graph
        </p>
      </div>

      {/* Message area */}
      <div style={{ flex: 1, overflowY: "auto", padding: "24px" }}>
        {messages.length === 0 ? (
          <div style={{ maxWidth: "640px", margin: "40px auto 0" }}>
            <div style={{ textAlign: "center", marginBottom: "40px" }}>
              <div style={{ width: "48px", height: "48px", borderRadius: "12px", background: "rgba(99,102,241,0.12)", border: "1px solid rgba(99,102,241,0.25)", display: "flex", alignItems: "center", justifyContent: "center", margin: "0 auto 16px" }}>
                <Telescope size={22} style={{ color: "var(--color-indigo)" }} />
              </div>
              <h2 style={{ fontSize: "18px", fontWeight: 600, margin: "0 0 8px" }}>Discovery Copilot</h2>
              <p style={{ color: "var(--color-text-secondary)", fontSize: "13px", margin: 0, lineHeight: 1.6 }}>
                Ask anything about the scientific knowledge graph. I reason over
                relationships, surface research gaps, and cite my sources.
              </p>
            </div>

            <p style={{ fontSize: "11px", color: "var(--color-text-muted)", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: "10px" }}>
              Example queries
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
              {EXAMPLE_QUERIES.map(q => (
                <button
                  key={q}
                  onClick={() => sendQuery(q)}
                  style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", padding: "10px 14px", textAlign: "left", cursor: "pointer", fontSize: "13px", color: "var(--color-text-secondary)", display: "flex", alignItems: "center", gap: "8px" }}
                >
                  <Zap size={12} style={{ color: "var(--color-indigo)", flexShrink: 0 }} />
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div style={{ maxWidth: "760px", margin: "0 auto", display: "flex", flexDirection: "column", gap: "24px" }}>
            {messages.map((msg, i) => (
              <div key={i} style={{ display: "flex", flexDirection: "column", gap: "8px", alignItems: msg.role === "user" ? "flex-end" : "flex-start" }}>

                {/* User message */}
                {msg.role === "user" && (
                  <div style={{ background: "var(--color-indigo)", color: "white", padding: "10px 14px", maxWidth: "80%", fontSize: "13px", lineHeight: 1.5 }}>
                    {msg.content}
                  </div>
                )}

                {/* Assistant message */}
                {msg.role === "assistant" && (
                  <div style={{ width: "100%" }}>
                    {/* Agent trace */}
                    {msg.thinking.length > 0 && (
                      <div style={{ marginBottom: "10px", display: "flex", flexDirection: "column", gap: "3px" }}>
                        {msg.thinking.map((t, ti) => (
                          <div key={ti} style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                            <div style={{ width: "6px", height: "6px", borderRadius: "50%", background: "var(--color-indigo)", opacity: 0.6 }} />
                            <span style={{ fontSize: "11px", color: "var(--color-text-muted)", fontFamily: "var(--font-mono)" }}>{t}</span>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Opportunities */}
                    {msg.opportunities.length > 0 && (
                      <div style={{ display: "flex", flexDirection: "column", gap: "6px", marginBottom: "12px" }}>
                        {msg.opportunities.map(opp => (
                          <Link key={opp.id} href={`/discover/${opp.id}`} style={{ textDecoration: "none" }}>
                            <div style={{ background: "rgba(245,158,11,0.06)", border: "1px solid rgba(245,158,11,0.25)", padding: "8px 12px", display: "flex", gap: "10px", alignItems: "center" }}>
                              <Zap size={12} style={{ color: "var(--color-amber)", flexShrink: 0 }} />
                              <div style={{ flex: 1 }}>
                                <p style={{ margin: 0, fontSize: "12px", fontWeight: 500, color: "var(--color-text-primary)" }}>{opp.title}</p>
                                <div style={{ display: "flex", gap: "4px", marginTop: "3px" }}>
                                  <Badge variant="indigo">{opp.domain_a}</Badge>
                                  <span style={{ fontSize: "10px", color: "var(--color-text-muted)", alignSelf: "center" }}>×</span>
                                  <Badge variant="amber">{opp.domain_b}</Badge>
                                </div>
                              </div>
                              <span style={{ fontFamily: "var(--font-mono)", fontSize: "14px", fontWeight: 500, color: "var(--color-amber)" }}>
                                {Math.round((opp.score ?? 0) * 100)}
                              </span>
                            </div>
                          </Link>
                        ))}
                      </div>
                    )}

                    {/* Response text */}
                    <div style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)", padding: "14px 16px" }}>
                      {msg.content ? (
                        <p style={{ margin: 0, fontSize: "13px", lineHeight: 1.7, color: "var(--color-text-primary)", whiteSpace: "pre-wrap" }}>
                          {msg.content}
                          {!msg.complete && (
                            <span style={{ display: "inline-block", width: "8px", height: "14px", background: "var(--color-indigo)", marginLeft: "2px", animation: "blink 1s step-end infinite", verticalAlign: "text-bottom" }} />
                          )}
                        </p>
                      ) : (
                        <div style={{ display: "flex", gap: "8px", alignItems: "center", color: "var(--color-text-muted)", fontSize: "12px" }}>
                          <Loader size={12} style={{ animation: "spin 1s linear infinite" }} />
                          Agents running...
                        </div>
                      )}
                    </div>

                    {/* Citations */}
                    {msg.citations.length > 0 && (
                      <div style={{ marginTop: "8px", display: "flex", flexWrap: "wrap", gap: "6px" }}>
                        {msg.citations.map(c => (
                          <div key={c.paper_id} style={{ display: "flex", alignItems: "center", gap: "5px", padding: "3px 8px", background: "var(--color-surface-2)", border: "1px solid var(--color-border)", fontSize: "11px" }}>
                            <BookOpen size={10} style={{ color: "var(--color-text-muted)" }} />
                            <span style={{ color: "var(--color-text-secondary)" }}>{c.title?.slice(0, 50)}…</span>
                            {c.year && <span style={{ fontFamily: "var(--font-mono)", color: "var(--color-text-muted)" }}>{c.year}</span>}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
            <div ref={scrollRef} />
          </div>
        )}
      </div>

      {/* Input */}
      <div style={{ padding: "16px 24px", background: "var(--color-surface)", borderTop: "1px solid var(--color-border)", flexShrink: 0 }}>
        <div style={{ maxWidth: "760px", margin: "0 auto", display: "flex", gap: "8px" }}>
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && !e.shiftKey && sendQuery(input)}
            placeholder="Ask about research opportunities, gaps, trends..."
            disabled={streaming}
            style={{ flex: 1, background: "var(--color-bg)", border: "1px solid var(--color-border)", color: "var(--color-text-primary)", padding: "10px 14px", fontSize: "13px", fontFamily: "var(--font-mono)", outline: "none", opacity: streaming ? 0.6 : 1 }}
          />
          <button
            onClick={() => sendQuery(input)}
            disabled={streaming || !input.trim()}
            style={{ background: "var(--color-indigo)", border: "none", color: "white", width: "40px", height: "40px", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", opacity: streaming || !input.trim() ? 0.5 : 1 }}
          >
            {streaming ? <Loader size={15} style={{ animation: "spin 1s linear infinite" }} /> : <Send size={15} />}
          </button>
        </div>
        <p style={{ maxWidth: "760px", margin: "6px auto 0", fontSize: "11px", color: "var(--color-text-muted)", textAlign: "center" }}>
          Powered by NVIDIA NIM · Reasons over {" "}
          <Link href="/" style={{ color: "var(--color-indigo)", textDecoration: "none" }}>knowledge graph</Link>
          {" "} · Sources cited inline
        </p>
      </div>

      <style>{`
        @keyframes blink { 0%,100% { opacity:1; } 50% { opacity:0; } }
        @keyframes spin  { to { transform: rotate(360deg); } }
      `}</style>
    </div>
  );
}
