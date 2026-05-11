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
    <div className="mt-2 flex flex-wrap gap-1.5">
      {suggestions.map((s) => (
        <button
          key={s}
          onClick={() => onPick(s)}
          className="rounded-full border border-border bg-surface-1 px-2.5 py-1 text-[11px] text-foreground/90 hover:border-primary/60 hover:bg-surface-2 transition-colors"
        >
          {s}
        </button>
      ))}
    </div>
  );
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
  const opts = payload.options;
  const followups: string[] = [];
  if (opts.enable_chains !== false) followups.push("Try without chains");
  if (opts.include_broker !== false) followups.push("Skip broker freight");
  followups.push("Show alternative plan");
  followups.push("Replan for tomorrow");

  return (
    <div className="mt-2 rounded-md border border-border bg-surface-1 p-2.5 text-xs">
      <div className="grid grid-cols-3 gap-2">
        <div>
          <div className="text-[9px] uppercase text-muted-foreground tracking-wider">Margin</div>
          <div className="font-semibold text-good tabular-nums">
            €{alt.total_fleet_margin_eur.toLocaleString()}
          </div>
        </div>
        <div>
          <div className="text-[9px] uppercase text-muted-foreground tracking-wider">Deadhead</div>
          <div className="font-semibold tabular-nums">
            {Math.round(alt.deadhead_ratio * 100)}%
          </div>
        </div>
        <div>
          <div className="text-[9px] uppercase text-muted-foreground tracking-wider">SLA</div>
          <div
            className={cn(
              "font-semibold tabular-nums",
              alt.unserved_customer_load_ids.length ? "text-warn" : "text-good",
            )}
          >
            {alt.customer_loads_served}/{alt.customer_loads_available}
          </div>
        </div>
      </div>
      {totalAlts > 1 && (
        <div className="mt-2 flex gap-1">
          {payload.plan.optimiser.alternatives.map((a) => (
            <button
              key={a.rank}
              onClick={() => onSelectAlt(a.rank)}
              className={cn(
                "rounded px-2 py-0.5 text-[10px] font-medium",
                a.rank === alt.rank
                  ? "bg-primary text-primary-foreground"
                  : "bg-surface-2 text-muted-foreground hover:text-foreground",
              )}
            >
              Plan {a.rank}
            </button>
          ))}
        </div>
      )}
      <FollowUpChips suggestions={followups} onPick={onPick} />
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
        className="flex-1 min-h-0 overflow-y-auto thin-scroll px-4 py-4 space-y-4"
      >
        {turns.length === 0 && (
          <div className="space-y-3">
            <div className="text-foreground/90 leading-relaxed">
              <span className="font-semibold">Bună ziua!</span> I'm your dispatcher
              assistant. The fleet is at the Cluj-Napoca depot — 10 vans available,
              35 freight loads visible in the pool right now.
            </div>
            <div className="text-xs text-muted-foreground">Try one of these to start:</div>
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
      <div className="border-t border-border bg-card p-3">
        <div className="flex items-end gap-2">
          <button
            onClick={toggleMic}
            className={cn(
              "shrink-0 rounded-md border border-border p-2 text-muted-foreground hover:text-foreground transition-colors",
              listening && "border-destructive text-destructive",
            )}
            title={listening ? "Stop listening" : "Voice input"}
          >
            {listening ? <MicOff size={16} /> : <Mic size={16} />}
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
            placeholder="Ask anything — e.g. 'Plan today's routes' or 'Why is van CJ-203 idle?'"
            className="flex-1 resize-none rounded-md border border-border bg-surface-1 px-3 py-2 text-sm placeholder:text-muted-foreground focus:border-primary/60 focus:outline-none max-h-32"
          />
          <button
            onClick={() => send()}
            disabled={!text.trim() || busy}
            className="shrink-0 rounded-md bg-primary p-2 text-primary-foreground hover:opacity-90 disabled:opacity-40 transition-opacity"
            title="Send"
          >
            <Send size={16} />
          </button>
        </div>
        {turns.length > 0 && (
          <button
            onClick={onClear}
            className="mt-2 inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
          >
            <Trash2 size={11} /> Clear conversation
          </button>
        )}
      </div>
    </div>
  );
}
