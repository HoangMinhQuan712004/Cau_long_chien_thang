"use client";

import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { ConfirmDialog } from "@/components/play-rooms/confirm-dialog";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, fieldErrorId } from "@/components/ui/field";
import { IconButton } from "@/components/ui/icon-button";
import { PlusIcon, TrashIcon } from "@/components/ui/icons";
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

/** Ngày Lễ / Tết của một năm: danh sách kẻ dòng (không bảng lồng khung). Thêm / xóa có hiệu lực ngay (API riêng, không nằm trong bản nháp bảng giá). */
export function HolidaysCard({ year, items, t }: { year: number; items: SpecialDay[]; t: Texts }) {
  const router = useRouter();
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<SpecialDay | null>(null);

  // Trả câu lỗi để ConfirmDialog hiện trong hộp, null khi xong
  async function remove(day: SpecialDay): Promise<string | null> {
    const res = await write((key) =>
      api.DELETE("/api/v1/booking/special-days/{special_day_id}", { params: { path: { special_day_id: day.id } }, headers: { "Idempotency-Key": key } }),
    );
    if (!res.ok) return errorText(res.error);
    setRemoving(null);
    toast(t.removed.replace("{name}", day.name));
    router.refresh();
    return null;
  }

  return (
    <Card bareOnMobile className="flex flex-col gap-3 sm:p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="min-w-0 text-base font-semibold">{t.title.replace("{year}", String(year))}</h2>
        <Button type="button" variant="secondary" onClick={() => setAdding(true)} className="shrink-0 whitespace-nowrap">
          <PlusIcon />
          {t.add}
        </Button>
      </div>
      {items.length === 0 ? (
        <p className="py-4 text-center text-ui text-muted">{t.empty}</p>
      ) : (
        <ul className="divide-y border-t">
          {items.map((d) => (
            <li key={d.id} className="flex items-center gap-3 py-2">
              <span className="w-28 shrink-0 text-sm tabular-nums sm:w-36">
                {formatDayMonth(d.date_from)}
                {d.date_to !== d.date_from ? ` – ${formatDayMonth(d.date_to)}` : ""}
              </span>
              <span className="min-w-0 flex-1 text-sm">{d.name}</span>
              <IconButton icon={<TrashIcon />} label={t.remove.replace("{name}", d.name)} variant="danger" onClick={() => setRemoving(d)} />
            </li>
          ))}
        </ul>
      )}

      {adding ? (
        <HolidayForm
          year={year}
          t={t}
          onClose={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            router.refresh();
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

function HolidayForm({ year, t, onClose, onSaved }: { year: number; t: Texts; onClose: () => void; onSaved: () => void }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [name, setName] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [banner, setBanner] = useState("");
  const [busy, setBusy] = useState(false);
  const ids = { from: useId(), to: useId(), name: useId() };

  const min = `${year}-01-01`;
  const max = `${year}-12-31`;
  const errFrom = !from ? t.errFrom : from < min || from > max ? t.errYear.replace("{year}", String(year)) : "";
  const errTo = to && (to < from || to.slice(0, 4) !== from.slice(0, 4)) ? t.errTo : "";
  const errName = !name.trim() ? t.errName : name.trim().length > 100 ? t.errNameLong : "";
  // Lỗi chỉ hiện sau lần bấm Thêm đầu tiên
  const err = (e: string) => (submitted && e ? e : undefined);
  const invalid = (e: string, id: string) => (submitted && e ? { "aria-invalid": true, "aria-describedby": fieldErrorId(id) } : {});

  async function submit() {
    setSubmitted(true);
    setBanner("");
    if (errFrom || errTo || errName) return;
    setBusy(true);
    try {
      const res = await write((key) =>
        api.POST("/api/v1/booking/special-days", { body: { date_from: from, date_to: to || null, name: name.trim() }, headers: { "Idempotency-Key": key } }),
      );
      if (!res.ok) {
        if (res.error.status === 401 || res.error.status === 403) toast(errorText(res.error), undefined, "error");
        else setBanner(errorText(res.error));
        return;
      }
      toast(t.added.replace("{name}", res.data.name));
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
      title={t.formTitle}
      footer={
        <div className="grid w-full grid-cols-2 gap-2">
          <Button type="button" variant="secondary" block onClick={onClose} disabled={busy}>
            {t.cancel}
          </Button>
          <Button type="button" block onClick={() => void submit()} loading={busy}>
            {busy ? t.adding : t.add}
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
    </Modal>
  );
}
