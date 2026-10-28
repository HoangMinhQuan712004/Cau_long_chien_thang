import type { Dictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import { type Availability, toHHmm } from "./use-slot-selection";

type SlotGridProps = {
  data: Availability;
  rows: number[];
  selected: Set<string>;
  isBusy: (courtId: number, minute: number) => boolean;
  onToggle: (key: string) => void;
  t: Dictionary["booking"];
};

// Lưới giờ × sân: bấm ô trống để chọn/bỏ chọn
export function SlotGrid({ data, rows, selected, isBusy, onToggle, t }: SlotGridProps) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[480px] border-collapse text-sm">
        <thead className="sticky top-0 bg-surface">
          <tr>
            <th className="w-20 border-b border-border p-2 text-left">{t.timeHeader}</th>
            {data.courts.map((c) => (
              <th key={c.court_id} className="border-b border-border p-2">
                {c.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((m) => (
            <tr key={m}>
              <td className="border-b border-border px-2 py-1 tabular-nums text-muted">{toHHmm(m)}</td>
              {data.courts.map((c) => {
                const key = `${c.court_id}|${m}`;
                const busy = isBusy(c.court_id, m);
                const active = selected.has(key);
                return (
                  <td key={key} className="border-b border-l border-border p-0.5">
                    <button
                      type="button"
                      disabled={busy}
                      aria-pressed={active}
                      aria-label={`${c.name} ${toHHmm(m)}${busy ? ` ${t.full}` : ""}`}
                      onClick={() => onToggle(key)}
                      // Đã kín: nền xám + gạch chéo; trống: xanh nhạt
                      className={cn(
                        "h-8 w-full rounded transition-colors",
                        busy
                          ? "cursor-not-allowed bg-border bg-hatch"
                          : active
                            ? "bg-primary"
                            : "bg-primary/15 hover:bg-primary/30",
                      )}
                    />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
