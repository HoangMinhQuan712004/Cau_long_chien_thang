import { cn } from "@/lib/cn";
import type { MonitorMatch } from "./types";

/** "21 : 18", bên thắng đậm; chưa có tỉ số ⇒ "–". */
export function Score({ m, className }: { m: MonitorMatch; className?: string }) {
  if (m.score_a === null || m.score_b === null) return <span className={cn("text-muted", className)}>–</span>;
  return (
    <span className={cn("tabular-nums", className)} aria-label={`Tỉ số ${m.score_a} : ${m.score_b}`}>
      <span className={m.winner === "a" ? "font-bold" : "text-muted"}>{m.score_a}</span>
      <span className="text-muted"> : </span>
      <span className={m.winner === "b" ? "font-bold" : "text-muted"}>{m.score_b}</span>
    </span>
  );
}
