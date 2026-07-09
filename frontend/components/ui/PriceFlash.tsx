"use client";

import { useEffect, useRef, useState } from "react";

interface PriceFlashProps {
  value: number;
  children: React.ReactNode;
  className?: string;
}

/** Wraps a price; briefly tints green/red when the value changes, then fades. */
export default function PriceFlash({
  value,
  children,
  className = "",
}: PriceFlashProps) {
  const prev = useRef(value);
  const [flash, setFlash] = useState<"up" | "down" | null>(null);
  const [key, setKey] = useState(0);

  useEffect(() => {
    if (value === prev.current) return;
    setFlash(value > prev.current ? "up" : "down");
    setKey((k) => k + 1);
    prev.current = value;
  }, [value]);

  return (
    <span
      key={key}
      className={`rounded px-1 ${flash ? `flash-${flash}` : ""} ${className}`}
    >
      {children}
    </span>
  );
}
