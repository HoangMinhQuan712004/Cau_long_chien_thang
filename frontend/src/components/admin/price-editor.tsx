"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Resource } from "@/components/admin/courts-manager";
import { UnsavedGuard } from "@/components/admin/unsaved-guard";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatDate, formatNumber, formatTime } from "@/lib/format";

type PriceTable = components["schemas"]["PriceTable"];
type Cell = components["schemas"]["PriceCellIn"];

const DAY_TYPES = [
  { key: "weekday", label: "Ngày thường" },
  { key: "weekend", label: "Cuối tuần (T7, CN)" },
  { key: "holiday", label: "Lễ, Tết" },
] as const;
const BANDS = [
  { key: "offpeak", label: "Thấp điểm" },
  { key: "peak", label: "Cao điểm" },
] as const;

const cellKey = (type: string, day: string, band: string) => `${type}|${day}|${band}`;
const digits = (v: string) => v.replace(/\D/g, "");

/**
 * Bảng giá 2 loại sân × 3 loại ngày × 2 khung. Mọi ô lưu một lần (PUT cả bảng kèm `version`).
 * Dùng `key={table.version}` ở trang cha để sau khi lưu / tải lại bản nháp được dựng mới.
 */
export function PriceEditor({ table, resources }: { table: PriceTable; resources: Resource[] }) {
  const router = useRouter();
  const original = new Map(table.prices.map((p) => [cellKey(p.resource_type_code, p.day_type, p.band), p.price_per_hour]));
  // Mọi ô sẽ được gửi lên (loại sân × loại ngày × khung); ô server chưa có thì để trống và bị chặn ở bước kiểm tra.
  const allKeys = table.resource_types.flatMap((t) =>
    DAY_TYPES.flatMap((d) => BANDS.map((b) => cellKey(t.code, d.key, b.key))),
  );
  const fromServer = () => Object.fromEntries(allKeys.map((k) => [k, original.has(k) ? String(original.get(k)) : ""]));
  const [draft, setDraft] = useState<Record<string, string>>(fromServer);
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);

  const isValid = (k: string) => /^[1-9]\d*$/.test(draft[k] ?? "");
  const changed = (k: string) => draft[k] !== String(original.get(k) ?? "");
  const dirty = allKeys.some(changed);
  const anyInvalid = allKeys.some((k) => !isValid(k));
  const showError = (k: string) => (submitted || touched.has(k)) && !isValid(k);

  function cancel() {
    setDraft(fromServer());
    setTouched(new Set());
    setSubmitted(false);
    router.refresh(); // tải lại bản mới nhất (nếu máy khác vừa đổi)
  }

  async function save() {
    setSubmitted(true);
    if (anyInvalid) return;
    const prices: Cell[] = table.resource_types.flatMap((t) =>
      DAY_TYPES.flatMap((d) =>
        BANDS.map((b) => ({
          resource_type_code: t.code,
          day_type: d.key,
          band: b.key,
          price_per_hour: Number(draft[cellKey(t.code, d.key, b.key)]),
        })),
      ),
    );
    setBusy(true);
    try {
      const res = await write((key) =>
        api.PUT("/api/v1/booking/prices", { body: { version: table.version, prices }, headers: { "Idempotency-Key": key } }),
      );
      if (!res.ok) {
        const stale = res.error.code === "E-CFG-7";
        toast(errorText(res.error), stale ? "Bấm Hủy thay đổi để tải lại bảng giá." : undefined, "error");
        return;
      }
      toast("Đã lưu bảng giá. Giá mới áp cho các khung chưa đặt.");
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  const savedAt = table.updated_at ? `${formatDate(table.updated_at)} ${formatTime(table.updated_at)}` : "chưa có";

  return (
    <div className="space-y-4">
      <UnsavedGuard dirty={dirty} />
      <div className="rounded-lg border border-border bg-surface">
        <div className="flex flex-wrap items-center gap-2 border-b border-border p-4">
          <h2 className="text-base font-semibold">Giá thuê sân (đồng/giờ)</h2>
          <p className="ml-auto text-xs text-muted">
            Lưu gần nhất: {savedAt}
            {table.updated_by ? ` · ${table.updated_by}` : ""}
          </p>
        </div>
        <div className="relative overflow-x-auto p-4">
          <table className="w-full min-w-[40rem] border-collapse text-sm">
            <thead>
              <tr>
                <th rowSpan={2} className="px-2 py-2 text-left font-medium">
                  Loại sân
                </th>
                {DAY_TYPES.map((d) => (
                  <th key={d.key} colSpan={2} className="border-b border-border px-2 py-2 text-center font-medium">
                    {d.label}
                  </th>
                ))}
              </tr>
              <tr className="text-xs text-muted">
                {DAY_TYPES.flatMap((d) =>
                  BANDS.map((b) => (
                    <th key={`${d.key}-${b.key}`} className="px-2 py-1 text-center font-medium">
                      {b.label}
                    </th>
                  )),
                )}
              </tr>
            </thead>
            <tbody>
              {table.resource_types.map((t) => {
                const codes = resources.filter((r) => r.resource_type_code === t.code).map((r) => r.code).sort();
                return (
                  <tr key={t.code} className="border-t border-border">
                    <th scope="row" className="px-2 py-3 text-left font-medium">
                      {t.name}
                      <span className="block text-xs font-normal text-muted">
                        {codes.length} sân
                        {codes.length ? ` · ${codes[0]}${codes.length > 1 ? ` – ${codes[codes.length - 1]}` : ""}` : ""}
                      </span>
                    </th>
                    {DAY_TYPES.flatMap((d) =>
                      BANDS.map((b) => {
                        const k = cellKey(t.code, d.key, b.key);
                        const bad = showError(k);
                        return (
                          <td key={k} className="px-1.5 py-2">
                            <input
                              inputMode="numeric"
                              value={draft[k] ? formatNumber(Number(draft[k])) : ""}
                              onChange={(e) => setDraft((cur) => ({ ...cur, [k]: digits(e.target.value) }))}
                              onBlur={() => setTouched((cur) => new Set(cur).add(k))}
                              aria-label={`${t.name} · ${d.label} · ${b.label} (đồng/giờ)`}
                              aria-invalid={bad || undefined}
                              className={`w-full min-w-24 rounded-md border px-2 py-1.5 text-right tabular-nums ${
                                bad ? "border-danger" : changed(k) ? "border-primary bg-primary-softer" : "border-border bg-background"
                              }`}
                            />
                          </td>
                        );
                      }),
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
          {submitted && anyInvalid ? (
            <p role="alert" className="mt-2 text-xs text-danger">
              Giá phải là số nguyên lớn hơn 0.
            </p>
          ) : null}
          <p className="mt-3 text-xs text-muted">
            Cao điểm = giờ cao điểm đặt riêng ở từng sân (tab Danh mục sân). Ngoài giờ đó là Thấp điểm. Sân mới tự nhận giá theo Loại sân.
          </p>
        </div>
      </div>

      <div className="sticky bottom-0 flex flex-wrap items-center gap-3 rounded-lg border border-border bg-surface p-3">
        <p className="text-xs text-muted">
          Giá mới áp cho khung chưa đặt; khung đã đặt giữ giá cũ. Nút Lưu bật khi có ô thay đổi.
        </p>
        <div className="ml-auto flex gap-2">
          <button
            type="button"
            onClick={cancel}
            disabled={!dirty || busy}
            className="rounded-md border border-border px-4 py-2 text-sm disabled:opacity-50"
          >
            Hủy thay đổi
          </button>
          <button
            type="button"
            onClick={save}
            disabled={!dirty || busy}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {busy ? "Đang lưu…" : "Lưu bảng giá"}
          </button>
        </div>
      </div>
    </div>
  );
}
