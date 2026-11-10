import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { formatDayMonth, formatTime, hhmm, vnDate } from "@/lib/format";
import type { Item } from "./types";
import { Group } from "./ui";

// Lịch sử đổi sân của một booking: mới nhất ở đầu – lịch hiện tại (thẻ xanh nhạt, nhãn "Hiện tại") rồi các lịch cũ từ gần nhất tới cũ nhất.
// API trả cũ trước mới sau nên đảo ở đây.
// Mỗi mốc cũ lấy from_* của từng lần đổi (lần sau bắt đầu từ to_* của lần trước nên không trùng mốc).

const slot = (code: string, name: string, date: string, start: string, end: string) =>
  `${code} · ${name} · ${formatDayMonth(date)} ${hhmm(start)}–${hhmm(end)}`;

// Chấm tròn trên đường dọc (tâm cách mép trái 0.3125rem); mỗi mốc tự vẽ đoạn nối xuống mốc sau, mốc cuối không vẽ
const DOT = "absolute top-1.5 left-0 z-10 size-2.5 rounded-full border-2 border-primary";
const ITEM = "relative pl-5 after:absolute after:-bottom-4.5 after:left-1 after:w-px after:bg-border-strong last:after:hidden";

export function MoveHistory({ item }: { item: Item }) {
  const moves = item.moves ?? [];
  if (!moves.length) return null;
  const s = item.schedule;
  return (
    <Group title="Lịch sử đổi sân">
      <ol className="space-y-3">
        <li className={cn(ITEM, "after:top-3")}>
          <span aria-hidden className={cn(DOT, "top-2.5 bg-primary")} />
          <div className="inline-flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg bg-primary-softer px-2.5 py-1.5">
            <span className="text-sm font-semibold tabular-nums">
              {slot(s.resource_codes.join(", "), s.resource_names.join(", "), s.play_date, s.start_time, s.end_time)}
            </span>
            <Badge variant="success">Hiện tại</Badge>
          </div>
        </li>
        {[...moves].reverse().map((m) => (
          <li key={m.moved_at} className={cn(ITEM, "flex flex-wrap items-baseline gap-x-3 after:top-3")}>
            <span aria-hidden className={cn(DOT, "bg-surface")} />
            <p className="text-sm text-danger tabular-nums line-through decoration-danger">
              {slot(m.from_code, m.from_name, m.date, m.from_start_time, m.from_end_time)}
            </p>
            <p className="min-w-0 text-xs break-words text-muted tabular-nums">
              Đổi lúc {formatDayMonth(vnDate(m.moved_at))} {formatTime(m.moved_at)} · bởi {m.moved_by}
              {m.reason ? ` · ${m.reason}` : ""}
            </p>
          </li>
        ))}
      </ol>
    </Group>
  );
}
