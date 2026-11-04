"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useState } from "react";
import { TrashIcon } from "@/components/ui/icons";
import { Modal } from "@/components/ui/modal";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorText, write, type ApiError } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatDayMonth, formatDayMonthYear, formatNumber, todayVn } from "@/lib/format";

type Schedule = Omit<components["schemas"]["ScheduleOut"], "peak_bands"> & { peak_bands: string[][] };
/** Sân như API trả về (khung cao điểm là mảng [từ, đến]; OpenAPI sinh kiểu tuple nên khai báo lại cho lỏng hơn). */
export type Resource = Omit<components["schemas"]["ResourceOut"], "schedule" | "pending_schedule"> & {
  schedule: Schedule | null;
  pending_schedule: Schedule | null;
};
type ResourceType = components["schemas"]["ResourceTypeOut"];
type Band = [string, string];

const TIMES = Array.from({ length: 49 }, (_, i) => hhmm(i * 30)); // 00:00 -> 24:00, bước 30 phút

function hhmm(min: number) {
  return `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
}
const toMin = (t: string) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3, 5));
const sortBands = (b: Band[]): Band[] => [...b].sort((x, y) => toMin(x[0]) - toMin(y[0]));
/** Backend có thể trả "HH:MM:SS"; chỉ lấy HH:MM. */
const t5 = (t: string) => t.slice(0, 5);
const addDays = (isoDate: string, n: number) => {
  const d = new Date(`${isoDate}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

type Form = {
  mode: "add" | "edit";
  code?: string;
  version?: number;
  name: string;
  type: string;
  open: string;
  close: string;
  peaks: Band[];
  active: boolean;
};

type Errors = { name?: string; close?: string; peaks: Record<number, string>; overlap?: string; overlapIdx?: number[] };

function validate(f: Form, others: Resource[]): Errors {
  const e: Errors = { peaks: {} };
  const name = f.name.trim();
  if (!name) e.name = "Vui lòng nhập Tên sân.";
  else if (name.length > 50) e.name = "Tên sân tối đa 50 ký tự.";
  else if (others.some((r) => r.code !== f.code && r.name.trim().toLowerCase() === name.toLowerCase())) {
    e.name = "Tên sân đã có. Vui lòng đặt tên khác.";
  }
  const o = toMin(f.open);
  const c = toMin(f.close);
  if (c - o < 60) e.close = "Giờ đóng cửa phải sau giờ mở cửa ít nhất 1 tiếng.";
  f.peaks.forEach((p, i) => {
    const from = toMin(p[0]);
    const to = toMin(p[1]);
    if (to - from < 30 || from < o || to > c) {
      e.peaks[i] = `Khung cao điểm phải dài ít nhất 30 phút và nằm trong giờ mở cửa (${f.open} – ${f.close}).`;
    }
  });
  for (let i = 0; i < f.peaks.length && !e.overlap; i++) {
    for (let j = i + 1; j < f.peaks.length; j++) {
      const a = f.peaks[i];
      const b = f.peaks[j];
      if (toMin(a[0]) < toMin(b[1]) && toMin(b[0]) < toMin(a[1])) {
        e.overlap = `Khung ${a[0]} – ${a[1]} và khung ${b[0]} – ${b[1]} bị chồng nhau.`;
        e.overlapIdx = [i, j];
        break;
      }
    }
  }
  return e;
}

const hasErrors = (e: Errors) => Boolean(e.name || e.close || e.overlap || Object.keys(e.peaks).length);

type Conflict = { code: string; date: string; start_time: string; end_time: string };

/** Lỗi từ server hiện ở đầu hộp thoại (E-CFG-3/4 kèm danh sách khung vướng). */
type Banner = { text: string; items?: Conflict[]; more?: number; reload?: boolean };

function bannerFrom(error: ApiError): Banner {
  const items = Array.isArray(error.extra.items) ? (error.extra.items as Conflict[]) : undefined;
  const more = typeof error.extra.more === "number" ? error.extra.more : 0;
  return { text: errorText(error), items, more, reload: error.code === "E-CFG-7" };
}

export function CourtsManager({
  resources,
  types,
  weekdayPrice,
}: {
  resources: Resource[];
  types: ResourceType[];
  /** Giá ngày thường, thấp điểm, theo mã loại sân (VND/giờ). */
  weekdayPrice: Record<string, number>;
}) {
  const router = useRouter();
  const [form, setForm] = useState<Form | null>(null);
  const [fresh, setFresh] = useState<string | null>(null);
  const typeName = new Map(types.map((t) => [t.code, t.name]));
  const active = resources.filter((r) => r.is_active).length;

  useEffect(() => {
    if (!fresh) return;
    const t = setTimeout(() => setFresh(null), 3000);
    return () => clearTimeout(t);
  }, [fresh]);

  const openAdd = () =>
    setForm({
      mode: "add",
      name: "",
      type: types[0]?.code ?? "thuong",
      open: "05:00",
      close: "22:00",
      peaks: [
        ["05:00", "07:00"],
        ["17:00", "21:00"],
      ],
      active: true,
    });

  const openEdit = (r: Resource) => {
    const s = r.pending_schedule ?? r.schedule; // giờ đã lưu gần nhất (kể cả giờ chờ áp dụng)
    setForm({
      mode: "edit",
      code: r.code,
      version: r.version,
      name: r.name,
      type: r.resource_type_code,
      open: s ? t5(s.open_time) : "05:00",
      close: s ? t5(s.close_time) : "22:00",
      peaks: s ? sortBands(s.peak_bands.map((p) => [t5(p[0]), t5(p[1])] as Band)) : [],
      active: r.is_active,
    });
  };

  return (
    <div className="rounded-lg border border-border bg-surface">
      <div className="flex flex-wrap items-center gap-3 border-b border-border p-4">
        <h2 className="text-base font-semibold">
          Danh sách sân ({resources.length}) · {active} hoạt động, {resources.length - active} ngừng
        </h2>
        <button
          type="button"
          onClick={openAdd}
          className="ml-auto rounded-md bg-primary px-4 py-2 text-sm font-medium text-white"
        >
          + Thêm sân
        </button>
      </div>

      {resources.length === 0 ? (
        <p className="p-6 text-center text-sm text-muted">Chưa có sân nào. Bấm “Thêm sân” để bắt đầu.</p>
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[44rem] text-left text-sm">
            <thead className="text-xs text-muted">
              <tr className="border-b border-border">
                <th className="px-4 py-2 font-medium">Mã</th>
                <th className="px-4 py-2 font-medium">Sân</th>
                <th className="px-4 py-2 font-medium">Loại sân</th>
                <th className="px-4 py-2 font-medium">Giờ mở cửa</th>
                <th className="px-4 py-2 text-right font-medium">Giá ngày thường (₫)</th>
                <th className="px-4 py-2 font-medium">Trạng thái</th>
                <th className="px-4 py-2 text-right font-medium">Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {resources.map((r) => (
                <tr
                  key={r.code}
                  className={`border-b border-border last:border-0 ${r.is_active ? "" : "opacity-60"} ${
                    fresh === r.code ? "bg-primary-softer" : ""
                  }`}
                >
                  <td className="px-4 py-3 font-mono text-xs">{r.code}</td>
                  <td className="px-4 py-3 font-medium">{r.name}</td>
                  <td className="px-4 py-3">{typeName.get(r.resource_type_code) ?? r.resource_type_name}</td>
                  <td className="px-4 py-3">
                    {r.schedule ? `${t5(r.schedule.open_time)} – ${t5(r.schedule.close_time)}` : "—"}
                    {r.pending_schedule ? (
                      <span className="mt-0.5 block text-xs text-muted">
                        → {t5(r.pending_schedule.open_time)} – {t5(r.pending_schedule.close_time)} từ{" "}
                        {formatDayMonth(r.pending_schedule.effective_from)}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums">
                    {weekdayPrice[r.resource_type_code] != null ? formatNumber(weekdayPrice[r.resource_type_code]) : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        r.is_active ? "bg-primary-softer text-primary" : "bg-border text-muted"
                      }`}
                    >
                      {r.is_active ? "Hoạt động" : "Ngừng hoạt động"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button type="button" onClick={() => openEdit(r)} className="text-primary hover:underline">
                      Sửa<span className="sr-only"> {r.name}</span>
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {form ? (
        <CourtFormDialog
          key={form.code ?? "new"}
          initial={form}
          resources={resources}
          types={types}
          onClose={() => setForm(null)}
          onSaved={(code) => {
            setFresh(code);
            setForm(null);
            router.refresh();
          }}
          onReload={() => {
            setForm(null);
            router.refresh();
            toast("Đã tải lại dữ liệu mới nhất.", undefined, "info");
          }}
        />
      ) : null}
    </div>
  );
}

function CourtFormDialog({
  initial,
  resources,
  types,
  onClose,
  onSaved,
  onReload,
}: {
  initial: Form;
  resources: Resource[];
  types: ResourceType[];
  onClose: () => void;
  onSaved: (code: string) => void;
  onReload: () => void;
}) {
  const [f, setF] = useState<Form>(initial);
  const [touched, setTouched] = useState<{ name?: boolean; hours?: boolean; peaks?: boolean }>({});
  const [submitted, setSubmitted] = useState(false);
  const [banner, setBanner] = useState<Banner | null>(null);
  const [busy, setBusy] = useState(false);
  const ids = { name: useId(), nameErr: useId(), open: useId(), close: useId(), closeErr: useId() };
  const edit = initial.mode === "edit";
  const err = validate(f, resources);
  const showName = submitted || touched.name;
  const showHours = submitted || touched.hours;
  const showPeaks = submitted || touched.peaks;
  const tomorrow = addDays(todayVn(), 1);
  const slots = Math.max(0, (toMin(f.close) - toMin(f.open)) / 30);

  const patch = (p: Partial<Form>) => setF((cur) => ({ ...cur, ...p }));
  const setPeak = (i: number, j: 0 | 1, v: string) => {
    setTouched((t) => ({ ...t, peaks: true }));
    setF((cur) => ({ ...cur, peaks: cur.peaks.map((p, k) => (k === i ? (j === 0 ? [v, p[1]] : [p[0], v]) : p) as Band) }));
  };

  async function submit() {
    setSubmitted(true);
    setBanner(null);
    if (hasErrors(err)) return;
    const peaks = sortBands(f.peaks);
    setBusy(true);
    try {
      if (!edit) {
        const res = await write((key) =>
          api.POST("/api/v1/booking/resources", {
            body: {
              name: f.name.trim(),
              resource_type_code: f.type,
              open_time: f.open,
              close_time: f.close,
              peak_bands: peaks,
            },
            headers: { "Idempotency-Key": key },
          }),
        );
        if (!res.ok) return fail(res.error);
        toast(`Đã thêm ${res.data.code} · ${res.data.name}. Khách đặt được ngay.`);
        onSaved(res.data.code);
        return;
      }

      const orig = resources.find((r) => r.code === f.code);
      const base = orig?.pending_schedule ?? orig?.schedule;
      const hoursChanged =
        !base ||
        f.open !== t5(base.open_time) ||
        f.close !== t5(base.close_time) ||
        JSON.stringify(peaks) !== JSON.stringify(sortBands(base.peak_bands.map((p) => [t5(p[0]), t5(p[1])] as Band)));
      const body: components["schemas"]["ResourceUpdate"] = { version: f.version ?? 0 };
      if (f.name.trim() !== orig?.name) body.name = f.name.trim();
      if (f.type !== orig?.resource_type_code) body.resource_type_code = f.type;
      if (f.active !== orig?.is_active) body.is_active = f.active;
      if (hoursChanged) {
        body.open_time = f.open;
        body.close_time = f.close;
        body.peak_bands = peaks;
      }
      if (Object.keys(body).length === 1) {
        onClose(); // không có gì thay đổi
        return;
      }
      const res = await write((key) =>
        api.PATCH("/api/v1/booking/resources/{code}", {
          params: { path: { code: f.code! } },
          body,
          headers: { "Idempotency-Key": key },
        }),
      );
      if (!res.ok) return fail(res.error);
      toast(
        hoursChanged
          ? `Đã lưu ${res.data.name}. Giờ mới áp dụng từ ${formatDayMonthYear(tomorrow)}.`
          : `Đã lưu ${res.data.name}.`,
      );
      onSaved(res.data.code);
    } finally {
      setBusy(false);
    }
  }

  function fail(error: ApiError) {
    if (error.status === 401 || error.status === 403) {
      toast(errorText(error), undefined, "error");
      return;
    }
    setBanner(bannerFrom(error));
  }

  return (
    <Modal
      open
      onClose={onClose}
      size="wide"
      title={edit ? `Sửa ${initial.name}` : "Thêm sân"}
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy} className="rounded-md border border-border px-4 py-2 text-sm">
            Hủy
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={busy}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
          >
            {busy ? "Đang lưu…" : edit ? "Lưu" : "Thêm sân"}
          </button>
        </>
      }
    >
      {banner ? (
        <div role="alert" className="rounded-md border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
          <p>{banner.text}</p>
          {banner.items?.length ? (
            <ul className="mt-1.5 list-disc pl-5">
              {banner.items.slice(0, 6).map((it) => (
                <li key={`${it.code}-${it.date}-${it.start_time}`}>
                  {it.code} · {formatDayMonth(it.date)} {t5(it.start_time)}–{t5(it.end_time)}
                </li>
              ))}
              {banner.more ? <li>… và {banner.more} khung khác</li> : null}
            </ul>
          ) : null}
          {banner.reload ? (
            <button type="button" onClick={onReload} className="mt-2 rounded-md border border-danger/50 px-3 py-1 text-xs font-medium">
              Tải lại
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-sm font-medium">Mã sân</label>
          <input
            readOnly
            value={initial.code ?? "Tự cấp khi thêm"}
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-muted"
          />
          <p className="mt-1 text-xs text-muted">Hệ thống cấp, cố định.</p>
        </div>
        <div>
          <label htmlFor={ids.name} className="mb-1 block text-sm font-medium">
            Tên sân <span className="text-danger">*</span>
          </label>
          <input
            id={ids.name}
            value={f.name}
            maxLength={50}
            placeholder="VD: Sân 7"
            onChange={(e) => patch({ name: e.target.value })}
            onBlur={() => setTouched((t) => ({ ...t, name: true }))}
            aria-invalid={Boolean(showName && err.name)}
            aria-describedby={showName && err.name ? ids.nameErr : undefined}
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
          />
          {showName && err.name ? (
            <p id={ids.nameErr} className="mt-1 text-xs text-danger">
              {err.name}
            </p>
          ) : null}
        </div>
      </div>

      <fieldset>
        <legend className="mb-1 text-sm font-medium">
          Loại sân <span className="text-danger">*</span>
        </legend>
        <div className="flex flex-wrap gap-4 text-sm">
          {types.map((t) => (
            <label key={t.code} className="flex items-center gap-2">
              <input type="radio" name="resource-type" checked={f.type === t.code} onChange={() => patch({ type: t.code })} />
              {t.name}
            </label>
          ))}
        </div>
        <p className="mt-1 text-xs text-muted">Giá thuê lấy theo Loại sân ở tab Bảng giá.</p>
      </fieldset>

      <div>
        <p className="mb-2 text-sm font-semibold">
          Giờ hoạt động{edit ? ` · áp dụng từ ngày mai, ${formatDayMonthYear(tomorrow)}` : ""}
        </p>
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label htmlFor={ids.open} className="mb-1 block text-sm font-medium">
              Mở cửa
            </label>
            <TimeSelect
              id={ids.open}
              value={f.open}
              onChange={(v) => {
                setTouched((t) => ({ ...t, hours: true }));
                patch({ open: v });
              }}
            />
          </div>
          <div>
            <label htmlFor={ids.close} className="mb-1 block text-sm font-medium">
              Đóng cửa
            </label>
            <TimeSelect
              id={ids.close}
              value={f.close}
              invalid={Boolean(showHours && err.close)}
              describedBy={showHours && err.close ? ids.closeErr : undefined}
              onChange={(v) => {
                setTouched((t) => ({ ...t, hours: true }));
                patch({ close: v });
              }}
            />
            {showHours && err.close ? (
              <p id={ids.closeErr} className="mt-1 text-xs text-danger">
                {err.close}
              </p>
            ) : null}
          </div>
          <div>
            <span className="mb-1 block text-sm font-medium">Số khung</span>
            {/* Cùng khung với hai ô chọn giờ bên cạnh để ba cột thẳng hàng */}
            <p className="rounded-md border border-transparent bg-background/60 px-3 py-2 text-sm text-muted">{slots} khung 30 phút mỗi ngày</p>
          </div>
        </div>
      </div>

      <fieldset>
        <legend className="mb-2 text-sm font-semibold">Giờ cao điểm</legend>
        <div className="space-y-2">
          {f.peaks.map((p, i) => {
            const bad = showPeaks && (err.peaks[i] || err.overlapIdx?.includes(i));
            return (
              <div key={i}>
                {/* Hàng khung giờ: Từ – Đến cùng cỡ cột Mở cửa / Đóng cửa phía trên, nút xóa là icon cùng chiều cao */}
                <div className={`grid grid-cols-[1fr_auto_1fr_auto] items-center gap-2 rounded-md sm:grid-cols-[minmax(0,10rem)_auto_minmax(0,10rem)_auto] ${bad ? "ring-1 ring-danger" : ""}`}>
                  <TimeSelect label="Từ" value={p[0]} onChange={(v) => setPeak(i, 0, v)} />
                  <span aria-hidden className="text-muted">
                    –
                  </span>
                  <TimeSelect label="Đến" value={p[1]} onChange={(v) => setPeak(i, 1, v)} />
                  <button
                    type="button"
                    title="Xóa khung giờ"
                    onClick={() => {
                      setTouched((t) => ({ ...t, peaks: true }));
                      setF((cur) => ({ ...cur, peaks: cur.peaks.filter((_, k) => k !== i) }));
                    }}
                    className="grid size-9 place-items-center rounded-md text-muted hover:bg-danger-soft hover:text-danger focus-ring"
                  >
                    <TrashIcon size={16} />
                    <span className="sr-only">Xóa khung cao điểm {i + 1}</span>
                  </button>
                </div>
                {showPeaks && err.peaks[i] ? <p className="mt-1 text-xs text-danger">{err.peaks[i]}</p> : null}
              </div>
            );
          })}
          {showPeaks && err.overlap ? <p className="text-xs text-danger">{err.overlap}</p> : null}
          <button
            type="button"
            onClick={() =>
              setF((cur) => ({
                ...cur,
                peaks: [...cur.peaks, [cur.open, hhmm(Math.min(toMin(cur.open) + 60, toMin(cur.close)))]],
              }))
            }
            className="text-sm text-primary hover:underline"
          >
            + Thêm khung giờ
          </button>
        </div>
        <p className="mt-2 text-xs text-muted">
          Các khung không được chồng nhau và phải nằm trong giờ mở cửa · giá cao điểm theo Loại sân ở tab Bảng giá.
        </p>
      </fieldset>

      {edit ? (
        <fieldset>
          <legend className="mb-1 text-sm font-medium">Trạng thái</legend>
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input type="radio" name="resource-active" checked={f.active} onChange={() => patch({ active: true })} />
              Hoạt động
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" name="resource-active" checked={!f.active} onChange={() => patch({ active: false })} />
              Ngừng hoạt động
            </label>
          </div>
          <p className="mt-1 text-xs text-muted">Ngừng: khách không thấy, không đặt được sân.</p>
        </fieldset>
      ) : null}
    </Modal>
  );
}

function TimeSelect({
  id,
  value,
  onChange,
  label,
  invalid,
  describedBy,
}: {
  id?: string;
  value: string;
  onChange: (v: string) => void;
  label?: string;
  invalid?: boolean;
  describedBy?: string;
}) {
  return (
    <select
      id={id}
      value={value}
      aria-label={label}
      aria-invalid={invalid || undefined}
      aria-describedby={describedBy}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
    >
      {TIMES.map((t) => (
        <option key={t} value={t}>
          {t}
        </option>
      ))}
    </select>
  );
}
