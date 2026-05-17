/**
 * Conversation panel — the dispatcher's only input surface.
 * Ported from the Lovable bundle; relative imports + minor tweaks for our
 * React 18 setup.
 */
import { useEffect, useRef, useState } from "react";
import { Mic, MicOff, Send, Trash2 } from "lucide-react";
import type { ChatTurn, PlanResponse } from "../../lib/dispatch-types";
import { cn } from "../../lib/utils";

interface Props {
  turns: ChatTurn[];
  busy: boolean;
  onSend: (text: string) => void;
  onClear: () => void;
  onSelectAlt: (rank: number) => void;
  activePlan: PlanResponse | null;
}

const QUICK_SUGGESTIONS_EMPTY = [
  "Plan today's routes",
  "Find loads for next week",
  "Show what compliance saves us",
];

function FollowUpChips({
  suggestions,
  onPick,
}: {
  suggestions: string[];
  onPick: (s: string) => void;
}) {
  if (!suggestions.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {suggestions.map((s) => (
        <button
          key={s}
          onClick={() => onPick(s)}
          className="rounded-full border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground hover:border-primary hover:text-primary hover:shadow-sm transition-all"
        >
          {s}
        </button>
      ))}
    </div>
  );
}

function vanColorOf(id: number): string {
  // Tiny inline copy of vanColor — keeps ChatPanel self-contained.
  const PALETTE = [
    "#22d3ee", "#a78bfa", "#f59e0b", "#34d399", "#f472b6",
    "#60a5fa", "#fb7185", "#facc15", "#4ade80", "#c084fc",
    "#fda4af", "#fbbf24", "#84cc16", "#38bdf8", "#fb923c",
  ];
  return PALETTE[id % PALETTE.length];
}

function PlanSummaryCard({
  turn,
  onPick,
  onSelectAlt,
}: {
  turn: ChatTurn;
  onPick: (s: string) => void;
  onSelectAlt: (rank: number) => void;
}) {
  if (!turn.payload || turn.payload.kind !== "plan") return null;
  const payload = turn.payload;
  const alt =
    payload.plan.optimiser.alternatives.find((a) => a.rank === payload.activeRank) ??
    payload.plan.optimiser.alternatives[0];
  if (!alt) return null;

  const totalAlts = payload.plan.optimiser.alternatives.length;
  const dispatched = alt.plans.length - alt.idle_count;
  const total = alt.plans.length;
  const activeVans = alt.plans.filter((p) => p.kind !== "IDLE");
  const followups: string[] = [];
  if (payload.options.include_broker !== false) followups.push("Skip broker freight");
  if (payload.options.enable_chains !== false) followups.push("Try without chains");
  followups.push("Replan for tomorrow");

  return (
    <div className="mt-3 overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      {/* Headline: 2 big stats, no jargon */}
      <div className="grid grid-cols-2 gap-px bg-border">
        <div className="bg-card px-4 py-3">
          <div className="text-[11px] font-medium text-muted-foreground">
            Today's profit
          </div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-good">
            €{Math.round(alt.total_fleet_margin_eur).toLocaleString()}
          </div>
        </div>
        <div className="bg-card px-4 py-3">
          <div className="text-[11px] font-medium text-muted-foreground">
            Vans on the road
          </div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-foreground">
            {dispatched}
            <span className="text-base font-normal text-muted-foreground"> of {total}</span>
          </div>
        </div>
      </div>

      {/* Per-van rows — one line each, hidden behind a disclosure to keep
          the chat scannable. */}
      {activeVans.length > 0 && (
        <details className="group border-t border-border">
          <summary className="cursor-pointer list-none px-4 py-2.5 text-xs font-medium text-muted-foreground hover:bg-surface-1">
            <span className="inline-flex items-center gap-1">
              <span className="transition-transform group-open:rotate-90">▸</span>
              See {activeVans.length} van{activeVans.length === 1 ? "" : "s"} dispatched
            </span>
          </summary>
          <ul className="space-y-px bg-border">
            {activeVans
              .slice()
              .sort((a, b) => b.margin_eur - a.margin_eur)
              .map((v) => {
                const cities = [v.legs[0]?.from_city ?? "Cluj"]
                  .concat(v.legs.map((l) => l.to_city))
                  .filter((c, i, arr) => i === 0 || arr[i - 1] !== c);
                return (
                  <li
                    key={v.van_id}
                    className="flex items-center gap-2 bg-card px-4 py-2 text-xs"
                  >
                    <span
                      className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                      style={{ background: vanColorOf(v.van_id) }}
                    />
                    <span
                      className="shrink-0 font-mono text-[11px] font-semibold"
                      style={{ color: vanColorOf(v.van_id) }}
                    >
                      {v.van_plate.replace("-CRL", "")}
                    </span>
                    {v.kind === "CHAIN" && (
                      <span className="shrink-0 rounded bg-good/10 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-good">
                        chain
                      </span>
                    )}
                    <span className="min-w-0 flex-1 truncate text-foreground/80">
                      {cities.join(" → ")}
                    </span>
                    <span className="shrink-0 font-semibold tabular-nums text-good">
                      €{Math.round(v.margin_eur)}
                    </span>
                  </li>
                );
              })}
          </ul>
        </details>
      )}

      {/* Alternatives + follow-ups footer */}
      <div className="border-t border-border bg-surface-1 px-4 py-2.5">
        {totalAlts > 1 && (
          <div className="mb-2 flex flex-wrap gap-1.5">
            {payload.plan.optimiser.alternatives.map((a) => (
              <button
                key={a.rank}
                onClick={() => onSelectAlt(a.rank)}
                className={cn(
                  "rounded-full px-2.5 py-1 text-[11px] font-medium transition-colors",
                  a.rank === alt.rank
                    ? "bg-primary text-primary-foreground"
                    : "bg-card text-muted-foreground hover:text-foreground border border-border",
                )}
              >
                Option {a.rank}
              </button>
            ))}
          </div>
        )}
        <FollowUpChips suggestions={followups} onPick={onPick} />
      </div>
    </div>
  );
}

function CompliancePayload({ turn }: { turn: ChatTurn }) {
  if (!turn.payload || turn.payload.kind !== "compliance") return null;
  return (
    <div className="mt-2 rounded-md border border-border bg-surface-1 p-2.5 text-xs">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
        Avoided fines
      </div>
      <div className="text-lg font-semibold text-good tabular-nums">
        €{turn.payload.saved_eur.toLocaleString()}
      </div>
      <div className="mt-2 space-y-1">
        {turn.payload.violations.map((v) => (
          <div key={v.rule} className="flex items-start justify-between gap-3">
            <span className="text-foreground/80">{v.rule}</span>
            <span className="font-mono text-warn">€{v.fine_eur}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function IdlePayload({ turn }: { turn: ChatTurn }) {
  if (!turn.payload || turn.payload.kind !== "idle_explain") return null;
  return (
    <div className="mt-2 rounded-md border border-border bg-surface-1 p-2.5 text-xs">
      <div className="font-mono text-foreground/90">{turn.payload.van_plate}</div>
      <ul className="mt-1.5 space-y-1 list-disc pl-4 text-foreground/80">
        {turn.payload.reasons.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
    </div>
  );
}

function ClarifyPayload({
  turn,
  onPick,
}: {
  turn: ChatTurn;
  onPick: (s: string) => void;
}) {
  if (!turn.payload || turn.payload.kind !== "clarify") return null;
  return <FollowUpChips suggestions={turn.payload.suggestions} onPick={onPick} />;
}

interface SpeechRecognitionLike {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: (e: { results: ArrayLike<{ 0: { transcript: string } }> }) => void;
  onend: () => void;
  start: () => void;
  stop: () => void;
}

export function ChatPanel({ turns, busy, onSend, onClear, onSelectAlt }: Props) {
  const [text, setText] = useState("");
  const [listening, setListening] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const recogRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [turns.length, busy]);

  function send(value?: string) {
    const v = (value ?? text).trim();
    if (!v || busy) return;
    onSend(v);
    setText("");
    setTimeout(() => inputRef.current?.focus(), 0);
  }

  function toggleMic() {
    const w = window as unknown as {
      SpeechRecognition?: new () => SpeechRecognitionLike;
      webkitSpeechRecognition?: new () => SpeechRecognitionLike;
    };
    const SR = w.SpeechRecognition ?? w.webkitSpeechRecognition;
    if (!SR) {
      alert("Voice input not supported in this browser.");
      return;
    }
    if (listening) {
      recogRef.current?.stop();
      setListening(false);
      return;
    }
    const r = new SR();
    r.lang = "en-US";
    r.interimResults = true;
    r.continuous = false;
    r.onresult = (e) => {
      const transcript = Array.from(e.results)
        .map((res) => res[0].transcript)
        .join("");
      setText(transcript);
    };
    r.onend = () => setListening(false);
    r.start();
    recogRef.current = r;
    setListening(true);
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Chat history */}
      <div
        ref={scrollRef}
        className="flex-1 min-h-0 overflow-y-auto thin-scroll px-5 py-6 space-y-5"
      >
        {turns.length === 0 && (
          <div className="space-y-4">
            <div>
              <div className="text-2xl">👋</div>
              <div className="mt-2 text-base leading-relaxed text-foreground">
                <span className="font-semibold">Bună ziua.</span> Ask me anything
                about today's freight — I'll plan the routes for your vans.
              </div>
            </div>
            <div className="text-xs uppercase tracking-wide text-muted-foreground">
              Try one of these
            </div>
            <FollowUpChips suggestions={QUICK_SUGGESTIONS_EMPTY} onPick={(s) => send(s)} />
          </div>
        )}

        {turns.map((t) => (
          <div
            key={t.id}
            className={cn("flex", t.role === "user" ? "justify-end" : "justify-start")}
          >
            <div className="max-w-[90%]">
              {t.role === "user" ? (
                <div className="chat-user-bubble rounded-2xl rounded-br-sm px-3.5 py-2 text-sm">
                  {t.content}
                </div>
              ) : (
                <div className="text-sm leading-relaxed text-foreground/95">
                  <div className="whitespace-pre-wrap">{t.content}</div>
                  <PlanSummaryCard
                    turn={t}
                    onPick={(s) => send(s)}
                    onSelectAlt={onSelectAlt}
                  />
                  <CompliancePayload turn={t} />
                  <IdlePayload turn={t} />
                  <ClarifyPayload turn={t} onPick={(s) => send(s)} />
                </div>
              )}
            </div>
          </div>
        ))}

        {busy && (
          <div className="flex justify-start">
            <div className="text-sm text-muted-foreground italic">Planning…</div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-border bg-card p-4">
        <div className="flex items-end gap-2 rounded-xl border border-border bg-card px-3 py-2 shadow-sm focus-within:border-primary/60 transition-colors">
          <button
            onClick={toggleMic}
            className={cn(
              "shrink-0 rounded-full p-1.5 text-muted-foreground hover:text-foreground hover:bg-surface-1 transition-colors",
              listening && "text-destructive",
            )}
            title={listening ? "Stop listening" : "Voice input"}
          >
            {listening ? <MicOff size={18} /> : <Mic size={18} />}
          </button>
          <textarea
            ref={inputRef}
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="Ask me anything…"
            className="flex-1 resize-none bg-transparent px-1 py-1.5 text-sm placeholder:text-muted-foreground focus:outline-none max-h-32"
          />
          <button
            onClick={() => send()}
            disabled={!text.trim() || busy}
            className="shrink-0 rounded-full bg-primary p-2 text-primary-foreground hover:opacity-90 disabled:opacity-40 transition-opacity"
            title="Send"
          >
            <Send size={16} />
          </button>
        </div>
        {turns.length > 0 && (
          <button
            onClick={onClear}
            className="mt-2 inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          >
            <Trash2 size={12} /> Clear conversation
          </button>
        )}
      </div>
    </div>
  );
}
