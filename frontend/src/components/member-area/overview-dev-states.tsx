"use client";

import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/cn";

// CHỈ DEV (NODE_ENV !== "production"): nút xem thử các trạng thái thẻ "Tiếp theo" ngay trên dữ liệu thật – đổi tại chỗ,
// không gọi API / ghi DB. Bản build production không render.

type Upcoming = components["schemas"]["UpcomingItem"];
export type NextPreview = "real" | "ongoing" | "later" | "other_day" | "full" | "no_room" | "none";

export const DEV_PREVIEW = process.env.NODE_ENV !== "production";

const OPTIONS: { key: NextPreview; label: string }[] = [
  { key: "real", label: "Thật" },
  { key: "ongoing", label: "Đang diễn ra" },
  { key: "later", label: "Sắp tới" },
  { key: "other_day", label: "Ngày khác" },
  { key: "full", label: "Phòng đầy 10/10" },
  { key: "no_room", label: "Chưa có phòng" },
  { key: "none", label: "Không có lịch" },
];

const MIN = 60_000;
const iso = (ms: number) => new Date(ms).toISOString();

/** Lịch "Tiếp theo" theo trạng thái đang xem thử (giờ dời theo mốc `nowMs`); `undefined` = không có lịch. */
export function previewNext(item: Upcoming | undefined, mode: NextPreview, nowMs: number, today: string): Upcoming | undefined {
  if (mode === "real") return item;
  if (mode === "none" || !item) return undefined;
  const at = (fromNow: number, phase: Upcoming["phase"]) => ({ ...item, phase, play_date: today, start_at: iso(nowMs + fromNow), end_at: iso(nowMs + fromNow + 120 * MIN) });
  if (mode === "ongoing") return at(-30 * MIN, "ongoing");
  if (mode === "later") return at(180 * MIN, "upcoming");
  if (mode === "other_day") {
    // Ngày mai 19h–21h giờ Việt Nam ⇒ thẻ hiện "dd/mm · 19h–21h" thay "Hôm nay"
    const day = new Date(Date.parse(`${today}T00:00:00Z`) + 1440 * MIN).toISOString().slice(0, 10);
    return { ...item, phase: "upcoming", play_date: day, start_at: `${day}T19:00:00+07:00`, end_at: `${day}T21:00:00+07:00` };
  }
  if (mode === "full") {
    // Phòng 10/10: API chỉ trả tối đa 4 avatar xem trước (PREVIEW = 4 ở backend)
    const names = ["Đức Búa", "Thao", "Minh", "Lan"];
    const preview = names.map((n, i) => item.members_preview[i] ?? { display_name: n, avatar_url: null });
    return { ...at(180 * MIN, "upcoming"), room_id: item.room_id ?? 0, capacity: 10, count: 10, members_preview: preview };
  }
  return { ...at(180 * MIN, "upcoming"), room_id: null, capacity: null, count: null, members_preview: [] };
}

export function NextPreviewBar({ value, onChange }: { value: NextPreview; onChange: (v: NextPreview) => void }) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-1.5 rounded-lg border border-dashed border-border-strong p-2 text-xs">
      <span className="font-semibold text-muted">Dev · xem thử:</span>
      {OPTIONS.map((o) => (
        <button
          key={o.key}
          type="button"
          aria-pressed={value === o.key}
          onClick={() => onChange(o.key)}
          className={cn("rounded-full px-2.5 py-1 font-semibold focus-ring", value === o.key ? "bg-primary text-surface" : "bg-background hover:bg-primary-softer")}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
