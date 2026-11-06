"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import type { Resource } from "@/components/admin/court-form-logic";
import { UnsavedGuard } from "@/components/admin/unsaved-guard";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { Dictionary } from "@/i18n/dictionaries";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorText, write } from "@/lib/api/write";
import { cn } from "@/lib/cn";
import { toast } from "@/lib/feedback";
import { formatDateTime, formatNumber } from "@/lib/format";
import { BANDS, cellKey, DAY_TYPES, PriceTree, type BandKey, type DayType, type PriceType } from "./price-tree";

type PriceTable = components["schemas"]["PriceTable"];
type Cell = components["schemas"]["PriceCellIn"];
type PriceTexts = Dictionary["prices"];

/**
 * Bảng giá loại sân × 3 loại ngày × 2 khung. Mọi ô lưu một lần (PUT cả bảng kèm `version`).
 * Dùng `key={table.version}` ở trang cha để sau khi lưu / tải lại bản nháp được dựng mới.
 * Trình bày ở PriceTree (cây gia phả ở tiêu đề). Thanh Lưu dính đáy.
 */
export function PriceEditor({ table, resources, t }: { table: PriceTable; resources: Resource[]; t: PriceTexts }) {
  const router = useRouter();
  const original = new Map(table.prices.map((p) => [cellKey(p.resource_type_code, p.day_type, p.band), p.price_per_hour]));
  // Mọi ô sẽ được gửi lên (loại sân × loại ngày × khung); ô server chưa có thì để trống và bị chặn ở bước kiểm tra.
  const allKeys = table.resource_types.flatMap((x) => DAY_TYPES.flatMap((d) => BANDS.map((b) => cellKey(x.code, d, b))));
  const fromServer = () => Object.fromEntries(allKeys.map((k) => [k, original.has(k) ? String(original.get(k)) : ""]));
  const [draft, setDraft] = useState<Record<string, string>>(fromServer);
  const [touched, setTouched] = useState<Set<string>>(new Set());
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);

  const isValid = (k: string) => /^[1-9]\d*$/.test(draft[k] ?? "");
  const changed = (k: string) => draft[k] !== String(original.get(k) ?? "");
  const changedCount = allKeys.filter(changed).length;
  const anyInvalid = allKeys.some((k) => !isValid(k));

  const courtCount = (type: string) => t.courtCount.replace("{n}", String(resources.filter((r) => r.resource_type_code === type).length));

  // Hàm dựng (không phải component) để ô giữ focus khi gõ
  const priceInput = (type: PriceType, day: DayType, band: BandKey) => {
    const k = cellKey(type.code, day, band);
    const isBad = (submitted || touched.has(k)) && !isValid(k);
    return (
      <Input
        key={band}
        inputMode="numeric"
        value={draft[k] ? formatNumber(Number(draft[k])) : ""}
        onChange={(e) => setDraft((cur) => ({ ...cur, [k]: e.target.value.replace(/\D/g, "") }))}
        onBlur={() => setTouched((cur) => new Set(cur).add(k))}
        aria-label={t.cellLabel.replace("{type}", type.name).replace("{day}", t.dayTypes[day]).replace("{band}", t.bands[band])}
        aria-invalid={isBad || undefined}
        className={cn("min-w-0 px-2! text-right tabular-nums", !isBad && changed(k) && "border-primary font-semibold text-primary")}
      />
    );
  };

  function cancel() {
    setDraft(fromServer());
    setTouched(new Set());
    setSubmitted(false);
    router.refresh(); // tải lại bản mới nhất (nếu máy khác vừa đổi)
  }

  async function save() {
    setSubmitted(true);
    if (anyInvalid) return;
    const prices: Cell[] = table.resource_types.flatMap((x) =>
      DAY_TYPES.flatMap((d) => BANDS.map((b) => ({ resource_type_code: x.code, day_type: d, band: b, price_per_hour: Number(draft[cellKey(x.code, d, b)]) }))),
    );
    setBusy(true);
    try {
      const res = await write((key) =>
        api.PUT("/api/v1/booking/prices", { body: { version: table.version, prices }, headers: { "Idempotency-Key": key } }),
      );
      if (!res.ok) {
        toast(errorText(res.error), res.error.code === "E-CFG-7" ? t.staleHint : undefined, "error");
        return;
      }
      toast(t.saved);
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  const savedAt = table.updated_at ? t.savedAt.replace("{at}", formatDateTime(table.updated_at)) : t.neverSaved;

  return (
    <div className="flex flex-col gap-3">
      <UnsavedGuard dirty={changedCount > 0} />
      <Card bareOnMobile className="flex flex-col gap-4 sm:p-5">
        {/* Điện thoại xuống 2 dòng căn trái; từ sm chung một hàng, kẻ ngang hết bề rộng khối */}
        <div className="flex flex-col gap-0.5 border-b pb-3 sm:-mx-5 sm:flex-row sm:px-5 sm:items-baseline sm:justify-between sm:gap-3">
          <h2 className="text-base font-semibold">{t.title}</h2>
          <span className="text-xs text-muted">{savedAt}</span>
        </div>
        <PriceTree types={table.resource_types} courtCount={courtCount} renderInput={priceInput} t={t} />
        {submitted && anyInvalid ? (
          <p role="alert" className="text-ui text-danger">
            {t.invalid}
          </p>
        ) : null}
      </Card>

      {/* Thanh Lưu dính đáy: một dòng gợi ý ngắn + 2 nút; điện thoại 2 nút rộng bằng nhau */}
      <div data-bottom-bar className="sticky bottom-0 z-10 flex flex-col gap-2 border-t bg-surface p-3 sm:flex-row sm:items-center sm:rounded-card sm:border sm:shadow-card">
        <p className="text-ui text-muted" aria-live="polite">
          {changedCount > 0 ? `${t.barDirty.replace("{n}", String(changedCount))} ` : ""}
          {t.barHint}
        </p>
        <div className="grid grid-cols-2 gap-2 sm:ml-auto sm:flex">
          <Button type="button" variant="secondary" onClick={cancel} disabled={changedCount === 0 || busy}>
            {t.cancel}
          </Button>
          <Button type="button" onClick={() => void save()} disabled={changedCount === 0} loading={busy}>
            {busy ? t.saving : t.save}
          </Button>
        </div>
      </div>
    </div>
  );
}
