"use client";

import { useRouter } from "next/navigation";
import { useId, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatDayMonth } from "@/lib/format";

type SpecialDay = components["schemas"]["SpecialDayOut"];

/** Ngày Lễ / Tết của một năm. Thêm / xóa có hiệu lực ngay (API riêng, không nằm trong bản nháp bảng giá). */
export function HolidaysCard({ year, items }: { year: number; items: SpecialDay[] }) {
  const router = useRouter();
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<SpecialDay | null>(null);
  const [busy, setBusy] = useState(false);

  async function remove(day: SpecialDay) {
    setBusy(true);
    try {
      const res = await write((key) =>
        api.DELETE("/api/v1/booking/special-days/{special_day_id}", {
          params: { path: { special_day_id: day.id } },
          headers: { "Idempotency-Key": key },
        }),
      );
      setRemoving(null);
      if (!res.ok) {
        toast(errorText(res.error), undefined, "error");
        return;
      }
      toast(`Đã xóa ${day.name}.`);
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-border bg-surface">
      <div className="flex items-center gap-3 border-b border-border p-4">
        <h2 className="text-base font-semibold">Ngày Lễ / Tết năm {year}</h2>
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="ml-auto rounded-md border border-border px-3 py-1.5 text-sm"
        >
          + Thêm ngày
        </button>
      </div>
      {items.length === 0 ? (
        <p className="p-6 text-center text-sm text-muted">Chưa có ngày Lễ / Tết.</p>
      ) : (
        <table className="w-full text-sm">
          <tbody>
            {items.map((d) => (
              <tr key={d.id} className="border-b border-border last:border-0">
                <td className="w-36 px-4 py-3 tabular-nums">
                  {formatDayMonth(d.date_from)}
                  {d.date_to !== d.date_from ? ` – ${formatDayMonth(d.date_to)}` : ""}
                </td>
                <td className="px-2 py-3">{d.name}</td>
                <td className="px-4 py-3 text-right">
                  <button type="button" onClick={() => setRemoving(d)} className="text-danger hover:underline">
                    Xóa<span className="sr-only"> {d.name}</span>
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {adding ? (
        <HolidayForm
          year={year}
          onClose={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            router.refresh();
          }}
        />
      ) : null}

      <Modal
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title="Xóa ngày Lễ / Tết?"
        footer={
          <>
            <button type="button" onClick={() => setRemoving(null)} disabled={busy} className="rounded-md border border-border px-4 py-2 text-sm">
              Hủy
            </button>
            <button
              type="button"
              onClick={() => removing && remove(removing)}
              disabled={busy}
              className="rounded-md bg-danger px-4 py-2 text-sm font-medium text-primary-fg disabled:opacity-60"
            >
              {busy ? "Đang xóa…" : "Xóa ngày"}
            </button>
          </>
        }
      >
        <p className="text-sm">
          Xóa “{removing?.name}” khỏi danh sách? Các khung chưa đặt trong những ngày này sẽ tính theo giá ngày thường / cuối tuần.
        </p>
      </Modal>
    </div>
  );
}

function HolidayForm({ year, onClose, onSaved }: { year: number; onClose: () => void; onSaved: () => void }) {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [name, setName] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [banner, setBanner] = useState("");
  const [busy, setBusy] = useState(false);
  const ids = { from: useId(), to: useId(), name: useId() };

  const min = `${year}-01-01`;
  const max = `${year}-12-31`;
  const errFrom = !from ? "Vui lòng nhập Từ ngày." : from < min || from > max ? `Chỉ nhập ngày trong năm ${year}.` : "";
  const errTo = to && (to < from || to.slice(0, 4) !== from.slice(0, 4)) ? "Đến ngày phải từ Từ ngày trở đi, trong cùng năm." : "";
  const errName = !name.trim() ? "Vui lòng nhập Tên ngày." : name.trim().length > 100 ? "Tên ngày tối đa 100 ký tự." : "";

  async function submit() {
    setSubmitted(true);
    setBanner("");
    if (errFrom || errTo || errName) return;
    setBusy(true);
    try {
      const res = await write((key) =>
        api.POST("/api/v1/booking/special-days", {
          body: { date_from: from, date_to: to || null, name: name.trim() },
          headers: { "Idempotency-Key": key },
        }),
      );
      if (!res.ok) {
        if (res.error.status === 401 || res.error.status === 403) toast(errorText(res.error), undefined, "error");
        else setBanner(errorText(res.error));
        return;
      }
      toast(`Đã thêm ${res.data.name}.`);
      onSaved();
    } finally {
      setBusy(false);
    }
  }

  const field = "w-full rounded-md border border-border bg-background px-3 py-2 text-sm";
  return (
    <Modal
      open
      onClose={onClose}
      title="Thêm ngày Lễ / Tết"
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy} className="rounded-md border border-border px-4 py-2 text-sm">
            Hủy
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={busy}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-fg disabled:opacity-60"
          >
            {busy ? "Đang thêm…" : "Thêm ngày"}
          </button>
        </>
      }
    >
      {banner ? (
        <p role="alert" className="rounded-md border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
          {banner}
        </p>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor={ids.from} className="mb-1 block text-sm font-medium">
            Từ ngày <span className="text-danger">*</span>
          </label>
          <input id={ids.from} type="date" min={min} max={max} value={from} onChange={(e) => setFrom(e.target.value)} aria-invalid={Boolean(submitted && errFrom) || undefined} className={field} />
          {submitted && errFrom ? <p className="mt-1 text-xs text-danger">{errFrom}</p> : null}
        </div>
        <div>
          <label htmlFor={ids.to} className="mb-1 block text-sm font-medium">
            Đến ngày
          </label>
          <input id={ids.to} type="date" min={from || min} max={max} value={to} onChange={(e) => setTo(e.target.value)} aria-invalid={Boolean(submitted && errTo) || undefined} className={field} />
          {submitted && errTo ? <p className="mt-1 text-xs text-danger">{errTo}</p> : <p className="mt-1 text-xs text-muted">Bỏ trống nếu chỉ 1 ngày.</p>}
        </div>
      </div>
      <div>
        <label htmlFor={ids.name} className="mb-1 block text-sm font-medium">
          Tên ngày <span className="text-danger">*</span>
        </label>
        <input id={ids.name} value={name} maxLength={100} placeholder="VD: Giỗ Tổ Hùng Vương" onChange={(e) => setName(e.target.value)} aria-invalid={Boolean(submitted && errName) || undefined} className={field} />
        {submitted && errName ? <p className="mt-1 text-xs text-danger">{errName}</p> : null}
      </div>
    </Modal>
  );
}
