import type { Dictionary } from "@/i18n/dictionaries";
import type { components } from "@/lib/api/schema";
import { formatTime, formatVnd } from "@/lib/format";

type BookingSummaryProps = {
  slots: components["schemas"]["SlotIn"][];
  courtName: (id: number) => string | undefined;
  total: number | null;
  isSubmitting: boolean;
  disabled: boolean;
  onSubmit: () => void;
  t: Dictionary["booking"];
};

// Thanh dính đáy: các khung giờ đã chọn, tổng tiền, nút "Đặt sân"
export function BookingSummary({ slots, courtName, total, isSubmitting, disabled, onSubmit, t }: BookingSummaryProps) {
  return (
    <div className="sticky bottom-0 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-border bg-surface p-4 shadow-sm">
      <div>
        <p className="text-sm text-muted">
          {slots.length
            ? slots
                .map((s) => `${courtName(s.court_id)}: ${formatTime(s.start)}–${formatTime(s.end)}`)
                .join(" · ")
            : t.noSelection}
        </p>
        <p className="text-lg font-semibold">{total !== null ? formatVnd(total) : "—"}</p>
      </div>
      <button
        type="button"
        onClick={onSubmit}
        disabled={disabled}
        className="rounded-md bg-primary px-5 py-2.5 font-medium text-surface disabled:opacity-50"
      >
        {isSubmitting ? t.submitting : t.submit}
      </button>
    </div>
  );
}
