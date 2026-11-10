"use client";

import { useCallback, useId, useRef, useState } from "react";
import { ConfirmDialog } from "@/components/play-rooms/confirm-dialog";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, fieldErrorId } from "@/components/ui/field";
import { IconButton } from "@/components/ui/icon-button";
import { ChevronLeftIcon, ChevronRightIcon, PencilIcon, PlusIcon, TrashIcon } from "@/components/ui/icons";
import { Input } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import type { Dictionary } from "@/i18n/dictionaries";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatDayMonth } from "@/lib/format";

type SpecialDay = components["schemas"]["SpecialDayOut"];
type Texts = Dictionary["holidays"];

const MIN_YEAR = 2000;
const MAX_YEAR = 2100;

/**
 * Ngày Lễ / Tết theo năm (T-063): bộ chuyển năm ‹ 2026 › (2000–2100), thêm / sửa / xóa có hiệu lực ngay (API riêng, không nằm
 * trong bản nháp bảng giá). Sửa / xóa không đổi giá các buổi đã đặt (chốt giá lúc đặt).
 */
export function HolidaysCard({ year: initialYear, items: initialItems, t }: { year: number; items: SpecialDay[]; t: Texts }) {
  const [year, setYear] = useState(initialYear);
  const [items, setItems] = useState(initialItems);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [form, setForm] = useState<{ edit: SpecialDay | null } | null>(null);
  const [removing, setRemoving] = useState<SpecialDay | null>(null);
  const latest = useRef(initialYear);

  const load = useCallback(
    async (y: number) => {
      latest.current = y;
      setLoading(true);
      let data: SpecialDay[] | undefined;
      try {
        data = (await api.GET("/api/v1/booking/special-days", { params: { query: { year: y } } })).data;
      } catch {
        data = undefined; // mất mạng: báo lỗi bên dưới
      }
      if (latest.current !== y) return; // đã chuyển sang năm khác
      setLoading(false);
      // Lỗi ⇒ xóa danh sách cũ để không hiện ngày của năm trước dưới tiêu đề năm mới
      setItems(data ?? []);
      setLoadError(data ? "" : t.loadError);
    },
    [t.loadError],
  );

  const go = (y: number) => {
    if (y < MIN_YEAR || y > MAX_YEAR) return;
    setYear(y);
    void load(y);
  };

  // Trả câu lỗi để ConfirmDialog hiện trong hộp, null khi xong
  async function remove(day: SpecialDay): Promise<string | null> {
    const res = await write((key) =>
      api.DELETE("/api/v1/booking/special-days/{special_day_id}", { params: { path: { special_day_id: day.id } }, headers: { "Idempotency-Key": key } }),
    );
    if (!res.ok) return errorText(res.error);
    setRemoving(null);
    toast(t.removed.replace("{name}", day.name));
    await load(year);
    return null;
  }

  return (
    <Card bareOnMobile className="flex flex-col gap-3 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-1">
          <h2 className="min-w-0 text-base font-semibold">{t.titleNoYear}</h2>
          {/* Bộ chuyển năm (T-063) */}
          <div className="flex items-center" role="group" aria-label={t.yearPicker}>
            <IconButton icon={<ChevronLeftIcon />} label={t.prevYear} disabled={year <= MIN_YEAR || loading} onClick={() => go(year - 1)} />
            <span className="min-w-12 text-center text-base font-semibold tabular-nums" aria-live="polite">
              {year}
            </span>
            <IconButton icon={<ChevronRightIcon />} label={t.nextYear} disabled={year >= MAX_YEAR || loading} onClick={() => go(year + 1)} />
          </div>
        </div>
        <Button type="button" variant="secondary" onClick={() => setForm({ edit: null })} className="shrink-0 whitespace-nowrap">
          <PlusIcon />
          {t.add}
        </Button>
      </div>
      {loadError ? <Alert variant="error">{loadError}</Alert> : null}
      <div className={loading ? "opacity-60" : ""} aria-busy={loading}>
        {items.length === 0 ? (
          <p className="py-4 text-center text-ui text-muted">{t.empty.replace("{year}", String(year))}</p>
        ) : (
          <ul className="divide-y border-t">
            {items.map((d) => (
              <li key={d.id} className="flex items-center gap-3 py-2">
                <span className="w-28 shrink-0 text-sm tabular-nums sm:w-36">
                  {formatDayMonth(d.date_from)}
                  {d.date_to !== d.date_from ? ` – ${formatDayMonth(d.date_to)}` : ""}
                </span>
                <span className="min-w-0 flex-1 text-sm">{d.name}</span>
                <IconButton icon={<PencilIcon />} label={t.edit.replace("{name}", d.name)} onClick={() => setForm({ edit: d })} />
                <IconButton icon={<TrashIcon />} label={t.remove.replace("{name}", d.name)} variant="danger" onClick={() => setRemoving(d)} />
              </li>
            ))}
          </ul>
        )}
      </div>

      {form ? (
        <HolidayForm
          key={form.edit?.id ?? "new"}
          year={year}
          edit={form.edit}
          t={t}
          onClose={() => setForm(null)}
          onSaved={() => {
            setForm(null);
            void load(year);
          }}
        />
      ) : null}
      {removing ? (
        <ConfirmDialog
          danger
          title={t.removeTitle.replace("{name}", removing.name)}
          body={<p className="text-ui text-muted">{t.removeBody}</p>}
          cancelLabel={t.cancel}
          confirmLabel={t.removeConfirm}
          onClose={() => setRemoving(null)}
          onConfirm={() => remove(removing)}
        />
      ) : null}
    </Card>
  );
}

/** Form dùng chung Thêm / Sửa: chỉ nhận ngày trong năm đang xem, khoảng không vắt qua năm (DB check same_year). */
function HolidayForm({ year, edit, t, onClose, onSaved }: { year: number; edit: SpecialDay | null; t: Texts; onClose: () => void; onSaved: () => void }) {
  const [from, setFrom] = useState(edit?.date_from ?? "");
  const [to, setTo] = useState(edit && edit.date_to !== edit.date_from ? edit.date_to : "");
  const [name, setName] = useState(edit?.name ?? "");
  const [submitted, setSubmitted] = useState(false);
  const [banner, setBanner] = useState("");
  const [busy, setBusy] = useState(false);
  const ids = { from: useId(), to: useId(), name: useId() };

  const min = `${year}-01-01`;
  const max = `${year}-12-31`;
  const errFrom = !from ? t.errFrom : from < min || from > max ? t.errYear.replace("{year}", String(year)) : "";
  const errTo = !to || !from ? "" : to.slice(0, 4) !== from.slice(0, 4) ? t.errCrossYear : to < from ? t.errTo : "";
  const errName = !name.trim() ? t.errName : name.trim().length > 100 ? t.errNameLong : "";
  // Lỗi chỉ hiện sau lần bấm gửi đầu tiên
  const err = (e: string) => (submitted && e ? e : undefined);
  const invalid = (e: string, id: string) => (submitted && e ? { "aria-invalid": true, "aria-describedby": fieldErrorId(id) } : {});

  async function submit() {
    setSubmitted(true);
    setBanner("");
    if (errFrom || errTo || errName) return;
    setBusy(true);
    try {
      const body = { date_from: from, date_to: to || null, name: name.trim() };
      const res = await write((key) =>
        edit
          ? api.PATCH("/api/v1/booking/special-days/{special_day_id}", {
              params: { path: { special_day_id: edit.id } },
              body,
              headers: { "Idempotency-Key": key },
            })
          : api.POST("/api/v1/booking/special-days", { body, headers: { "Idempotency-Key": key } }),
      );
      if (!res.ok) {
        if (res.error.status === 401 || res.error.status === 403) toast(errorText(res.error), undefined, "error");
        else setBanner(errorText(res.error));
        return;
      }
      toast((edit ? t.saved : t.added).replace("{name}", res.data.name));
      onSaved();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      sheet
      onClose={onClose}
      title={edit ? t.editTitle : t.formTitle}
      footer={
        <div className="grid w-full grid-cols-2 gap-2">
          <Button type="button" variant="secondary" block onClick={onClose} disabled={busy}>
            {t.cancel}
          </Button>
          <Button type="button" block onClick={() => void submit()} loading={busy}>
            {edit ? (busy ? t.saving : t.save) : busy ? t.adding : t.add}
          </Button>
        </div>
      }
    >
      {banner ? <Alert variant="error">{banner}</Alert> : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t.from} htmlFor={ids.from} error={err(errFrom)}>
          <Input id={ids.from} type="date" min={min} max={max} value={from} onChange={(e) => setFrom(e.target.value)} {...invalid(errFrom, ids.from)} />
        </Field>
        <Field label={t.to} htmlFor={ids.to} error={err(errTo)} hint={t.toHint}>
          <Input id={ids.to} type="date" min={from || min} max={max} value={to} onChange={(e) => setTo(e.target.value)} {...invalid(errTo, ids.to)} />
        </Field>
      </div>
      <Field label={t.name} htmlFor={ids.name} error={err(errName)}>
        <Input id={ids.name} value={name} maxLength={100} placeholder={t.namePlaceholder} onChange={(e) => setName(e.target.value)} {...invalid(errName, ids.name)} />
      </Field>
      <p className="text-xs text-muted">{edit ? t.priceNote : t.yearNote.replace("{year}", String(year))}</p>
    </Modal>
  );
}
