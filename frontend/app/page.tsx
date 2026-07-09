"use client";

import { useState } from "react";
import { MarketProvider } from "@/lib/store";
import Header from "@/components/Header";
import Watchlist from "@/components/Watchlist";
import MainChart from "@/components/MainChart";
import PnlChart from "@/components/PnlChart";
import Heatmap from "@/components/Heatmap";
import PositionsTable from "@/components/PositionsTable";
import TradeBar from "@/components/TradeBar";
import ChatPanel from "@/components/ChatPanel";

function Dashboard() {
  const [chatOpen, setChatOpen] = useState(true);

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <Header />
      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="grid min-h-0 flex-1 grid-cols-[300px_1fr] gap-2 p-2">
            <Watchlist />
            <div className="grid min-h-0 min-w-0 grid-rows-[1.15fr_1fr] gap-2">
              <div className="grid min-h-0 min-w-0 grid-cols-[1.5fr_1fr] gap-2">
                <MainChart />
                <PnlChart />
              </div>
              <div className="grid min-h-0 min-w-0 grid-cols-2 gap-2">
                <Heatmap />
                <PositionsTable />
              </div>
            </div>
          </div>
          <TradeBar />
        </div>

        {chatOpen ? (
          <div className="w-[340px] shrink-0">
            <ChatPanel onCollapse={() => setChatOpen(false)} />
          </div>
        ) : (
          <button
            onClick={() => setChatOpen(true)}
            className="flex w-9 shrink-0 flex-col items-center gap-3 border-l border-border bg-panel py-3 text-muted transition-colors hover:text-ink"
            aria-label="Open chat"
          >
            <span className="text-purple">‹</span>
            <span
              className="text-[10px] font-semibold uppercase tracking-[0.2em]"
              style={{ writingMode: "vertical-rl" }}
            >
              Copilot
            </span>
          </button>
        )}
      </div>
    </div>
  );
}

export default function Home() {
  return (
    <MarketProvider>
      <Dashboard />
    </MarketProvider>
  );
}
