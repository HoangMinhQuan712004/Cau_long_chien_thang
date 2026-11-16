import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { FORMAT_LABEL, MAX_MEMBERS } from "../types";
import { hourRange, tierRangeText } from "../utils";
import { teamNames } from "./person";
import { Score } from "./score";
import { STATUS_LABEL, STATUS_VARIANT } from "./status";
import type { MonitorRoom } from "./types";

/** Thẻ một phòng trong hàng của sân: bấm mở chi tiết chỉ đọc. */
export function MonitorRoomCard({ room: r, onOpen }: { room: MonitorRoom; onOpen: () => void }) {
  const tier = tierRangeText({ min: r.min_tier, max: r.max_tier });
  const dim = r.status === "cancelled" || r.status === "ended";
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "flex w-full flex-col gap-2 rounded-xl border bg-surface p-3 text-left shadow-card hover:bg-primary-softer focus-ring",
        r.status === "playing" ? "border-primary/50 ring-1 ring-primary/20" : "border-border",
        dim && "opacity-90",
      )}
    >
      <span className="flex items-center justify-between gap-2">
        <b className="text-base tabular-nums">{hourRange(r.start_at, r.end_at)}</b>
        <Badge variant={STATUS_VARIANT[r.status]}>{STATUS_LABEL[r.status]}</Badge>
      </span>
      <span className="flex items-center justify-between gap-2 text-sm">
        <span className="min-w-0 truncate">
          Host: <b className="font-semibold">{r.host.nickname || r.host.full_name}</b>
        </span>
        <span className="shrink-0 font-semibold tabular-nums" aria-label={`${r.member_count} trên ${MAX_MEMBERS} người`}>
          {r.member_count}/{MAX_MEMBERS} <span className="font-normal text-muted">người</span>
        </span>
      </span>
      <span className="flex flex-wrap gap-1.5 text-xs text-muted">
        <span className="rounded-full bg-background px-2 py-0.5 ring-1 ring-border">{FORMAT_LABEL[r.format]}</span>
        <span className="rounded-full bg-background px-2 py-0.5 ring-1 ring-border">{tier ?? "Không có hạng"}</span>
        <span className="rounded-full bg-background px-2 py-0.5 ring-1 ring-border tabular-nums">{r.booking_code}</span>
      </span>
      <MatchLine room={r} />
    </button>
  );
}

/** Trận đang đánh (chỉ "Đang đánh", hệ thống không có tỉ số từng điểm) hoặc trận gần nhất kèm tỉ số. */
function MatchLine({ room: r }: { room: MonitorRoom }) {
  const m = r.current_match;
  const last = r.last_match;
  return (
    <span className="mt-auto block rounded-lg bg-background px-3 py-2 text-sm">
      {m ? (
        <>
          <span className="flex items-center gap-1.5 text-xs font-bold text-primary">
            <span aria-hidden className="size-2 animate-pulse rounded-full bg-primary motion-reduce:animate-none" />
            Đang đánh · Trận #{m.no}
          </span>
          <span className="block truncate">
            {teamNames(m.team_a)} <span className="text-muted">vs</span> {teamNames(m.team_b)}
          </span>
        </>
      ) : last ? (
        <>
          <span className="flex items-center justify-between gap-2 text-xs text-muted">
            <span>Trận gần nhất · #{last.no}</span>
            <Score m={last} className="text-base text-foreground" />
          </span>
          <span className="block truncate">
            {teamNames(last.team_a)} <span className="text-muted">vs</span> {teamNames(last.team_b)}
          </span>
        </>
      ) : (
        <span className="text-muted">Chưa có trận nào</span>
      )}
      <span className="mt-1 block text-xs text-muted">Đã xong {r.matches_finished} trận</span>
    </span>
  );
}
