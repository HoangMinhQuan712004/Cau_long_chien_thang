import type { PriceRule } from "@/lib/api/server";
import { DAY_NAMES, formatVnd } from "@/lib/format";

const hhmm = (t: string) => t.slice(0, 5);

export function PriceTable({ rules }: { rules: PriceRule[] }) {
  const general = rules.filter((r) => r.court_id == null);
  if (!general.length) return <p className="text-muted">Bảng giá đang được cập nhật.</p>;

  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full text-left text-sm">
        <thead className="border-b border-border">
          <tr>
            <th className="p-3">Khung giờ</th>
            <th className="p-3">Ngày áp dụng</th>
            <th className="p-3 text-right">Giá / giờ</th>
          </tr>
        </thead>
        <tbody>
          {general.map((r) => (
            <tr key={r.id} className="border-b border-border last:border-0">
              <td className="p-3 tabular-nums">
                {hhmm(r.start_time)} – {hhmm(r.end_time)}
              </td>
              <td className="p-3">{r.days_of_week.map((d) => DAY_NAMES[d]).join(", ")}</td>
              <td className="p-3 text-right font-semibold">{formatVnd(r.price_per_hour)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
