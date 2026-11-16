import type { PublicPrices } from "@/lib/api/server";
import { formatDayMonth, formatVnd } from "@/lib/format";

const DAY_TYPES = [
  { key: "weekday", label: "Ngày thường" },
  { key: "weekend", label: "Cuối tuần (T7, CN)" },
  { key: "holiday", label: "Lễ, Tết" },
] as const;
const BANDS = [
  { key: "offpeak", label: "Thấp điểm" },
  { key: "peak", label: "Cao điểm" },
] as const;

const hhmm = (t: string) => t.slice(0, 5);

/** Bảng giá thuê sân công khai: mỗi loại sân một bảng (khung × loại ngày), kèm giờ cao điểm. */
export function PriceTable({ data }: { data: PublicPrices | null }) {
  if (!data || !data.prices.length) return <p className="text-muted">Bảng giá đang được cập nhật.</p>;

  const price = (type: string, day: string, band: string) =>
    data.prices.find((p) => p.resource_type_code === type && p.day_type === day && p.band === band)?.price_per_hour;

  return (
    <div className="space-y-6">
      {data.resource_types.map((t) => {
        const peaks = data.peak_bands.find((b) => b.resource_type_code === t.code)?.bands ?? [];
        return (
          <section key={t.code} aria-labelledby={`price-${t.code}`} className="space-y-2">
            <h3 id={`price-${t.code}`} className="text-lg font-semibold">
              {t.name}
              <span className="ml-2 text-sm font-normal text-muted">{t.resource_count} sân</span>
            </h3>
            <div className="relative overflow-x-auto rounded-lg border border-border bg-surface">
              <table className="w-full text-left text-sm">
                <caption className="sr-only">Giá thuê {t.name} (đồng/giờ)</caption>
                <thead className="border-b border-border">
                  <tr>
                    <th scope="col" className="p-3">
                      Khung giờ
                    </th>
                    {DAY_TYPES.map((d) => (
                      <th key={d.key} scope="col" className="p-3 text-right">
                        {d.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {BANDS.map((b) => (
                    <tr key={b.key} className="border-b border-border last:border-0">
                      <th scope="row" className="p-3 font-medium">
                        {b.label}
                      </th>
                      {DAY_TYPES.map((d) => {
                        const v = price(t.code, d.key, b.key);
                        return (
                          <td key={d.key} className="p-3 text-right font-semibold tabular-nums">
                            {v == null ? "—" : formatVnd(v)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {peaks.length ? (
              <p className="text-sm text-muted">Giờ cao điểm: {peaks.map(([a, b]) => `${hhmm(a)} – ${hhmm(b)}`).join(", ")}.</p>
            ) : null}
          </section>
        );
      })}
      {data.special_days.length ? (
        <p className="text-sm text-muted">
          Ngày Lễ, Tết: {data.special_days.map((d) => `${d.name} (${formatDayMonth(d.date_from)}${d.date_to !== d.date_from ? `–${formatDayMonth(d.date_to)}` : ""})`).join("; ")}.
        </p>
      ) : null}
    </div>
  );
}
