"use client";

import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";
import { formatTime } from "@/lib/format";
import { roomsApi } from "./requests";
import { type Format, FORMAT_LABEL, type MatchList, type Person, type RankingRow } from "./types";

type FormatFilter = Format | "all";
const FILTERS: [FormatFilter, string][] = [
  ["all", "Tất cả"],
  ["2v2", "2 vs 2"],
  ["1v1", "1 vs 1"],
];

const names = (ps: Person[]) => ps.map((p) => p.display_name).join(" · ");

function FormatFilterBar({ value, onChange }: { value: FormatFilter; onChange: (f: FormatFilter) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Lọc thể thức">
      <span className="text-sm text-muted">Thể thức</span>
      {FILTERS.map(([k, label]) => (
        <button
          key={k}
          type="button"
          aria-pressed={value === k}
          onClick={() => onChange(k)}
          className={cn("h-8 rounded-full border px-3.5 text-sm font-medium focus-ring", value === k ? "border-primary-hover bg-primary-hover text-surface" : "border-border-strong hover:bg-primary-softer")}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

/** Tab "Lịch sử trận đấu": sub-tab Các trận / Xếp hạng trong phạm vi một phòng (T-017 AC19, AC20). */
export function RoomHistory({ roomId }: { roomId: number }) {
  const [sub, setSub] = useState<"matches" | "ranking">("matches");
  const [format, setFormat] = useState<FormatFilter>("all");
  const [matches, setMatches] = useState<MatchList | null>(null);
  const [ranking, setRanking] = useState<RankingRow[] | null>(null);
  const [error, setError] = useState(false);

  // Tải lại khi đổi bộ lọc / có trận mới (mốc 2: thêm polling khi BE có ETag)
  useEffect(() => {
    let alive = true;
    void Promise.all([roomsApi.listMatches(roomId, format), roomsApi.getRanking(roomId, format)]).then(([m, r]) => {
      if (!alive) return;
      if (m.ok && r.ok) {
        setMatches(m.data);
        setRanking(r.data);
        setError(false);
      } else setError(true);
    }).catch(() => alive && setError(true));
    return () => {
      alive = false;
    };
  }, [roomId, format]);

  return (
    <div className="space-y-4">
      <div className="flex gap-1 border-b border-border" role="tablist" aria-label="Lịch sử trận đấu">
        {(
          [
            ["matches", `Các trận${matches ? ` (${matches.total})` : ""}`],
            ["ranking", "Xếp hạng"],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={sub === k}
            onClick={() => setSub(k)}
            className={cn("-mb-px border-b-2 px-4 py-2.5 text-sm font-medium focus-ring", sub === k ? "border-primary font-bold text-primary" : "border-transparent text-muted hover:text-foreground")}
          >
            {label}
          </button>
        ))}
      </div>

      {error ? (
        <p role="alert" className="rounded-card bg-surface p-6 text-center text-sm text-danger shadow-card">
          Không tải được dữ liệu. Vui lòng thử lại sau.
        </p>
      ) : !matches || !ranking ? (
        <p className="py-8 text-center text-muted" aria-busy>
          Đang tải…
        </p>
      ) : sub === "matches" ? (
        <>
          <div className="grid grid-cols-3 gap-3">
            {[
              ["Tổng số trận", matches.total],
              ["2 vs 2", matches.by_format["2v2"]],
              ["1 vs 1", matches.by_format["1v1"]],
            ].map(([label, n]) => (
              <div key={label} className="rounded-card bg-surface p-3 shadow-card sm:p-4">
                <p className="text-xs text-muted sm:text-sm">{label}</p>
                <p className="mt-1 text-xl font-bold tabular-nums sm:text-2xl">{n}</p>
              </div>
            ))}
          </div>
          <FormatFilterBar value={format} onChange={setFormat} />
          <div className="relative overflow-x-auto rounded-card bg-surface shadow-card">
            <table className="w-full min-w-[40rem] text-left text-sm">
              <thead className="text-muted">
                <tr className="border-b border-border">
                  <th className="px-4 py-3 font-medium">Trận</th>
                  <th className="px-3 py-3 font-medium">Giờ</th>
                  <th className="px-3 py-3 font-medium">Thể thức</th>
                  <th className="px-3 py-3 font-medium">Đội A</th>
                  <th className="px-3 py-3 text-center font-medium">Tỉ số</th>
                  <th className="px-3 py-3 font-medium">Đội B</th>
                  <th className="px-4 py-3 font-medium">Thắng</th>
                </tr>
              </thead>
              <tbody>
                {matches.items.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-muted">
                      Chưa có trận nào được lưu.
                    </td>
                  </tr>
                ) : (
                  matches.items.map((m) => (
                    <tr key={m.no} className="border-b border-border last:border-0">
                      <td className="px-4 py-3 font-semibold">#{m.no}</td>
                      <td className="px-3 py-3 tabular-nums">{formatTime(m.ended_at)}</td>
                      <td className="px-3 py-3">{FORMAT_LABEL[m.format]}</td>
                      <td className="px-3 py-3">{names(m.team_a)}</td>
                      <td className="px-3 py-3 text-center tabular-nums">
                        <span className={m.winner === "A" ? "font-bold" : "text-muted"}>{m.score_a}</span>
                        <span className="text-muted"> : </span>
                        <span className={m.winner === "B" ? "font-bold" : "text-muted"}>{m.score_b}</span>
                      </td>
                      <td className="px-3 py-3">{names(m.team_b)}</td>
                      <td className="px-4 py-3 font-medium">Đội {m.winner}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <>
          <FormatFilterBar value={format} onChange={setFormat} />
          <p className="text-sm text-muted">Xếp theo số trận thắng · bằng nhau thì xét tỉ lệ thắng</p>
          <div className="relative overflow-x-auto rounded-card bg-surface shadow-card">
            <table className="w-full min-w-[36rem] text-left text-sm">
              <thead className="text-muted">
                <tr className="border-b border-border">
                  <th className="px-4 py-3 font-medium">Hạng</th>
                  <th className="px-3 py-3 font-medium">Người chơi</th>
                  <th className="px-3 py-3 text-right font-medium">Thắng</th>
                  <th className="px-3 py-3 text-right font-medium">Thua</th>
                  <th className="px-3 py-3 text-right font-medium">Số trận</th>
                  <th className="px-4 py-3 font-medium">Tỉ lệ thắng</th>
                </tr>
              </thead>
              <tbody>
                {ranking.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-muted">
                      Chưa có trận nào được lưu.
                    </td>
                  </tr>
                ) : (
                  ranking.map((r) => (
                    <tr key={`${r.rank}-${r.person.display_name}`} className={cn("border-b border-border last:border-0", r.person.is_me && "bg-primary-softer")}>
                      <td className="px-4 py-3">
                        <Medal rank={r.rank} />
                      </td>
                      <td className="px-3 py-3 font-medium">
                        {r.person.display_name}
                        {r.person.is_me ? <span className="ml-2 rounded-full bg-surface px-2 py-0.5 text-xs font-semibold ring-1 ring-border">Bạn</span> : null}
                      </td>
                      <td className="px-3 py-3 text-right tabular-nums">{r.wins}</td>
                      <td className="px-3 py-3 text-right tabular-nums">{r.losses}</td>
                      <td className="px-3 py-3 text-right tabular-nums">{r.played}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-24 overflow-hidden rounded-full bg-border" aria-hidden>
                            <div className="h-full rounded-full bg-primary" style={{ width: `${r.win_rate}%` }} />
                          </div>
                          <span className="tabular-nums">{r.win_rate}%</span>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

/** Hạng 1 vàng, 2 bạc (đồng hạng cùng màu); còn lại là số. */
function Medal({ rank }: { rank: number }) {
  if (rank > 2) return <span className="inline-grid size-7 place-items-center font-semibold tabular-nums">{rank}</span>;
  return (
    <span
      className={cn("inline-grid size-7 place-items-center rounded-full text-sm font-bold tabular-nums", rank === 1 ? "bg-accent text-foreground" : "bg-border-strong text-foreground")}
      aria-label={`Hạng ${rank}`}
    >
      {rank}
    </span>
  );
}
