"use client";

import { useEffect, useRef, useState } from "react";
import { useChat } from "@/lib/hooks";
import type { ChatAction, ChatMessage } from "@/lib/types";

const ACTION_STYLE: Record<
  ChatAction["kind"],
  { color: string; glyph: string }
> = {
  trade: { color: "var(--color-up)", glyph: "✓" },
  watchlist: { color: "var(--color-blue)", glyph: "★" },
  error: { color: "var(--color-down)", glyph: "!" },
};

function ActionChip({ action }: { action: ChatAction }) {
  const s = ACTION_STYLE[action.kind];
  return (
    <div
      className="flex items-center gap-1.5 rounded border px-2 py-1 text-[11px]"
      style={{ borderColor: `${s.color}40`, color: s.color }}
    >
      <span className="font-bold">{s.glyph}</span>
      <span className="text-ink/90">{action.text}</span>
    </div>
  );
}

function Bubble({ m }: { m: ChatMessage }) {
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-lg rounded-br-sm bg-blue/15 px-3 py-2 text-[13px] text-ink">
          {m.content}
        </div>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-1.5">
      <div className="max-w-[90%] rounded-lg rounded-bl-sm border border-border bg-panel-2 px-3 py-2 text-[13px] text-ink">
        {m.pending ? <TypingDots /> : m.content}
      </div>
      {m.actions?.length ? (
        <div className="flex max-w-[90%] flex-col gap-1 pl-1">
          {m.actions.map((a, i) => (
            <ActionChip key={i} action={a} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function TypingDots() {
  return (
    <span className="inline-flex gap-1">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted"
          style={{ animationDelay: `${i * 120}ms` }}
        />
      ))}
    </span>
  );
}

export default function ChatPanel({ onCollapse }: { onCollapse: () => void }) {
  const { chat, chatBusy, sendChat } = useChat();
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [chat]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || chatBusy) return;
    sendChat(input);
    setInput("");
  }

  return (
    <div className="flex h-full min-h-0 flex-col border-l border-border bg-panel">
      <header className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="flex items-center gap-2">
          <span className="h-3 w-[3px] rounded-full bg-purple" />
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted">
            FinAlly Copilot
          </h2>
        </div>
        <button
          onClick={onCollapse}
          aria-label="Collapse chat"
          className="rounded px-1.5 text-muted transition-colors hover:text-ink"
        >
          ›
        </button>
      </header>

      <div
        ref={scrollRef}
        className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3"
      >
        {chat.map((m) => (
          <Bubble key={m.id} m={m} />
        ))}
      </div>

      <form onSubmit={submit} className="border-t border-border p-2">
        <div className="flex items-end gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask FinAlly, or say “buy 10 NVDA”…"
            aria-label="Message FinAlly"
            className="min-w-0 flex-1 rounded border border-border bg-bg px-3 py-2 text-[13px] outline-none placeholder:text-faint focus:border-purple"
          />
          <button
            type="submit"
            disabled={chatBusy || !input.trim()}
            className="rounded bg-purple px-3 py-2 text-[13px] font-semibold text-white transition-opacity disabled:opacity-40"
          >
            Send
          </button>
        </div>
      </form>
    </div>
  );
}
