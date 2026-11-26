"use client";

import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { authFailure } from "@/components/booking-engine/booking-dialogs";
import { btnCls, btnDangerCls, btnPrimaryCls, ErrorBanner, inputCls } from "@/components/booking-engine/ui";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { DateRange } from "@/components/ui/date-range";
import { addDaysIso, formatDate, formatTime, todayVn } from "@/lib/format";
import { formatPhone } from "@/lib/phone";
import { RecordPlayer } from "./record-player";
import { type AdminRecordRow as AdminSpeedRecord, type AdminSpeedRecordList, getAdminSpeedRecords, SOURCE_LABEL, sendAdminDeleteRecord, sendApproveRecord, sendRejectRecord, sendRemoveRecordVideo } from "./requests";

// /admin/ky-luc (T-046 + T-047, chỉ Admin): số đo mới nhất trước, lọc Có video / Chưa có, gỡ video; xóa số đo nhập tay cũ;
// tab "Chờ duyệt" để duyệt / từ chối số đo hội viên đã gửi trước đây. 25/11 (người dùng): số đo + video chỉ đến từ camera AI –
// bỏ "+ Thêm số đo", "Sửa số đo" và gắn / sửa link video.
// Người dùng 21/11: mỗi dòng hiện họ tên thật, SĐT đầy đủ, giới tính của người đánh; lọc Tuần này / Tháng này / Tất cả + khoảng ngày đo.

const SIZE = 20;
const FILTERS = [
  { key: "all", label: "Tất cả" },
  { key: "yes", label: "Có video" },
  { key: "no", label: "Chưa có video" },
] as const;
type Filter = (typeof FILTERS)[number]["key"];
type Tab = "all" | "pending";
type Period = "week" | "month" | "all" | "custom";
const PERIODS = [
  { key: "week", label: "Tuần này" },
  { key: "month", label: "Tháng này" },
  { key: "all", label: "Tất cả" },
] as const;
const GENDER_LABEL = { male: "Nam", female: "Nữ" } as const;

/** Thứ Hai → Chủ nhật của tuần chứa `today` (YYYY-MM-DD, giờ VN). */
function weekOf(today: string): { from: string; to: string } {
  const weekday = (new Date(`${today}T00:00:00Z`).getUTCDay() + 6) % 7; // 0 = Thứ Hai
  const from = addDaysIso(today, -weekday);
  return { from, to: addDaysIso(from, 6) };
}

/** Ngày 1 → ngày cuối của tháng chứa `today`. */
function monthOf(today: string): { from: string; to: string } {
  const from = `${today.slice(0, 8)}01`;
  const next = new Date(`${from}T00:00:00Z`);
  next.setUTCMonth(next.getUTCMonth() + 1);
  return { from, to: addDaysIso(next.toISOString().slice(0, 10), -1) };
}

export function AdminRecordsScreen() {
  const [tab, setTab] = useState<Tab>("all");
  const [filter, setFilter] = useState<Filter>("all");
  const [pending, setPending] = useState(0);
  const [del, setDel] = useState<AdminSpeedRecord | null>(null);
  const [reject, setReject] = useState<AdminSpeedRecord | null>(null);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<AdminSpeedRecordList | null>(null);
  const [error, setError] = useState("");
  const [remove, setRemove] = useState<AdminSpeedRecord | null>(null);
  // Bấm số đo có video ⇒ popup phát video (người dùng 26/11)
  const [watch, setWatch] = useState<AdminSpeedRecord | null>(null);
  const [period, setPeriod] = useState<Period>("all");
  const [custom, setCustom] = useState<{ from: string; to: string }>({ from: "", to: "" });
  const [rangeError, setRangeError] = useState("");
  const today = useMemo(() => todayVn(), []);
  // Khoảng ngày đang áp: Tuần / Tháng tính theo hôm nay; Tất cả ⇒ không gửi from / to
  const range = period === "week" ? weekOf(today) : period === "month" ? monthOf(today) : period === "custom" ? custom : null;
  const rangeFrom = range?.from;
  const rangeTo = range?.to;
  const maxDate = [weekOf(today).to, monthOf(today).to].sort().at(-1) ?? today;

  const load = useCallback(async () => {
    const dates = { from: rangeFrom, to: rangeTo };
    const res = await getAdminSpeedRecords(tab === "pending" ? { status: "pending", page, size: SIZE, ...dates } : { has_video: filter === "all" ? undefined : filter === "yes", page, size: SIZE, ...dates });
    if (res.ok) {
      setPending(res.data.pending_count); // không phụ thuộc bộ lọc
      setData(res.data);
      setError("");
    } else if (!authFailure(res.error)) setError(errorText(res.error));
  }, [tab, filter, page, rangeFrom, rangeTo]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải khi đổi bộ lọc / trang
    void load();
  }, [load]);

  const pages = data ? Math.max(1, Math.ceil(data.total / data.size)) : 1;
  const chip = (on: boolean) => `rounded-full border px-3 py-1.5 text-sm ${on ? "border-primary bg-primary text-white" : "border-border bg-surface hover:bg-primary-softer"}`;

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-bold sm:text-2xl">Kỷ lục &amp; video</h1>
      <p className="text-sm text-muted">Số đo và video đến tự động từ camera AI (máy đo). Bảng xếp hạng và Video &amp; kỷ lục của hội viên chỉ tính số đo máy đo; số đo nhập tay cũ vẫn xem được ở đây.</p>

      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Danh sách số đo">
        {(
          [
            { key: "all", label: "Tất cả" },
            { key: "pending", label: `Chờ duyệt (${pending})` },
          ] as const
        ).map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => {
              setTab(t.key);
              setPage(1);
            }}
            className={chip(tab === t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className={`flex flex-wrap gap-2 ${tab === "pending" ? "hidden" : ""}`} role="group" aria-label="Lọc theo video">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            type="button"
            aria-pressed={filter === f.key}
            onClick={() => {
              setFilter(f.key);
              setPage(1);
            }}
            className={chip(filter === f.key)}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Lọc theo ngày đo: Tuần này / Tháng này / Tất cả, hoặc tự chọn Từ ngày – Đến ngày */}
      <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-3 sm:flex-row sm:flex-wrap sm:items-center sm:gap-3">
        <div className="flex flex-wrap gap-2" role="group" aria-label="Lọc theo thời gian đo">
          {PERIODS.map((p) => (
            <button
              key={p.key}
              type="button"
              aria-pressed={period === p.key}
              onClick={() => {
                setPeriod(p.key);
                setRangeError("");
                setPage(1);
              }}
              className={chip(period === p.key)}
            >
              {p.label}
            </button>
          ))}
        </div>
        <DateRange
          from={range?.from ?? ""}
          to={range?.to ?? ""}
          max={maxDate}
          linked={false}
          invalid={rangeError ? "from" : null}
          onChange={(next) => {
            if (next.from > next.to) {
              setRangeError("Từ ngày phải trước hoặc bằng Đến ngày.");
              return;
            }
            setRangeError("");
            setCustom(next);
            setPeriod("custom");
            setPage(1);
          }}
          t={{ from: "Từ ngày", to: "Đến ngày" }}
        />
        {rangeError ? (
          <p role="alert" className="text-sm text-danger">
            {rangeError}
          </p>
        ) : null}
      </div>

      {error && !data ? (
        <div role="alert" className="space-y-2 rounded-lg border border-border bg-surface p-6 text-center text-sm">
          <p className="text-danger">{error}</p>
          <button type="button" onClick={() => void load()} className={btnCls}>
            Thử lại
          </button>
        </div>
      ) : !data ? (
        <p className="py-10 text-center text-muted" aria-busy>
          Đang tải…
        </p>
      ) : data.items.length === 0 ? (
        <p className="rounded-lg border border-border bg-surface p-8 text-center text-muted">{tab === "pending" ? "Không có số đo nào chờ duyệt." : filter === "all" && !range ? "Chưa có số đo nào." : "Không có số đo nào khớp bộ lọc."}</p>
      ) : (
        <ul className="space-y-3">
          {data.items.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 rounded-xl border border-border bg-surface p-4 shadow-card">
              <div className="min-w-0">
                <p className="flex flex-wrap items-baseline gap-x-2">
                  {r.video ? (
                    <button type="button" onClick={() => setWatch(r)} className="inline-flex items-baseline gap-x-2 rounded-sm text-left focus-ring hover:text-primary" aria-label={`Xem video ${r.speed_kmh} km/h`}>
                      <b className="text-xl tabular-nums">{r.speed_kmh} km/h</b>
                      <span className="rounded-full bg-primary-softer px-2 py-0.5 text-xs font-semibold text-primary">▶ {r.video.kind === "youtube" ? "YouTube" : "File video"}</span>
                    </button>
                  ) : (
                    <>
                      <b className="text-xl tabular-nums">{r.speed_kmh} km/h</b>
                      <span className="rounded-full bg-background px-2 py-0.5 text-xs text-muted">Chưa có video</span>
                    </>
                  )}
                  <span className="rounded-full border border-border px-2 py-0.5 text-xs text-muted">{SOURCE_LABEL[r.source]}</span>
                  {r.status === "pending" ? <span className="rounded-full bg-cta px-2 py-0.5 text-xs font-semibold text-cta-fg">Chờ duyệt</span> : null}
                  {r.status === "rejected" ? <span className="rounded-full bg-danger px-2 py-0.5 text-xs font-semibold text-white">Bị từ chối</span> : null}
                </p>
                {/* Người đánh: họ tên thật + Mã HV, biệt danh (nếu khác); SĐT đầy đủ · giới tính (chỉ Admin thấy) */}
                <p className="text-sm font-semibold break-words">
                  {r.full_name ?? r.member_name}
                  {r.member_code ? <span className="ml-1.5 rounded bg-background px-1.5 py-0.5 font-mono text-xs font-normal text-muted">{r.member_code}</span> : null}
                  {r.full_name && r.member_name !== r.full_name && r.member_name !== "—" ? <span className="ml-1.5 font-normal text-accent-fg">“{r.member_name}”</span> : null}
                </p>
                {r.phone || r.gender ? (
                  <p className="text-sm text-foreground/80 tabular-nums">
                    {r.phone ? <a href={`tel:${r.phone}`} className="hover:text-primary hover:underline">{formatPhone(r.phone)}</a> : null}
                    {r.phone ? " · " : null}
                    {r.gender ? GENDER_LABEL[r.gender] : "Chưa nhập giới tính"}
                  </p>
                ) : null}
                <p className="text-xs text-muted tabular-nums">
                  {formatDate(r.measured_at)} · {formatTime(r.measured_at)}
                  {r.resource_name ? ` · ${r.resource_name}` : ""}
                </p>
                {r.status === "rejected" && r.reject_reason ? <p className="text-xs text-danger">Lý do: {r.reject_reason}</p> : null}
              </div>
              <div className="flex flex-wrap gap-2">
                {r.status === "pending" ? (
                  <>
                    <ApproveButton record={r} onDone={() => void load()} />
                    <button type="button" onClick={() => setReject(r)} className={btnCls}>
                      Từ chối
                    </button>
                  </>
                ) : null}
                {r.video ? (
                  <>
                    <button type="button" onClick={() => setWatch(r)} className={btnPrimaryCls}>
                      ▶ Xem video
                    </button>
                    <button type="button" onClick={() => setRemove(r)} className={btnCls}>
                      Gỡ video
                    </button>
                  </>
                ) : null}
                {r.editable ? (
                  <button type="button" onClick={() => setDel(r)} className={btnCls}>
                    Xóa
                  </button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}

      {data && pages > 1 ? (
        <nav aria-label="Phân trang" className="flex items-center justify-center gap-3">
          <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} className={btnCls}>
            ‹ Trước
          </button>
          <span className="text-sm text-muted" aria-live="polite">
            Trang {page}/{pages}
          </span>
          <button type="button" onClick={() => setPage((p) => Math.min(pages, p + 1))} disabled={page >= pages} className={btnCls}>
            Sau ›
          </button>
        </nav>
      ) : null}

      {watch?.video ? (
        <Modal open onClose={() => setWatch(null)} size="wide" title={`${watch.speed_kmh} km/h · ${watch.full_name ?? watch.member_name}`} subtitle={`${formatDate(watch.measured_at)} · ${formatTime(watch.measured_at)}${watch.resource_name ? ` · ${watch.resource_name}` : ""}`}>
          <RecordPlayer video={watch.video} speed={watch.speed_kmh} name={watch.full_name ?? watch.member_name} />
        </Modal>
      ) : null}
      {del ? (
        <DeleteDialog
          record={del}
          onClose={() => setDel(null)}
          onDone={() => {
            setDel(null);
            void load();
          }}
        />
      ) : null}
      {reject ? (
        <RejectDialog
          record={reject}
          onClose={() => setReject(null)}
          onDone={() => {
            setReject(null);
            void load();
          }}
        />
      ) : null}
      {remove ? (
        <RemoveDialog
          record={remove}
          onClose={() => setRemove(null)}
          onRemoved={() => {
            setRemove(null);
            void load();
          }}
        />
      ) : null}
    </div>
  );
}

function RemoveDialog({ record, onClose, onRemoved }: { record: AdminSpeedRecord; onClose: () => void; onRemoved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");
  async function go() {
    if (busy) return;
    setBusy(true);
    setBanner("");
    try {
      const res = await write((key) => sendRemoveRecordVideo(key, record.id));
      if (!res.ok) {
        if (!authFailure(res.error)) setBanner(errorText(res.error));
        return;
      }
      toast("Đã gỡ video", `${record.speed_kmh} km/h · ${record.member_name}`);
      onRemoved();
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      open
      onClose={onClose}
      title="Gỡ video?"
      footer={
        <>
          <button type="button" onClick={onClose} className={btnCls} disabled={busy}>
            Hủy
          </button>
          <button type="button" onClick={() => void go()} disabled={busy} className={btnDangerCls}>
            {busy ? "Đang gỡ…" : "Gỡ video"}
          </button>
        </>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      <p className="text-sm">
        Gỡ video của số đo <b>{record.speed_kmh} km/h</b> ({record.member_name}). Số đo vẫn còn trong bảng xếp hạng.
      </p>
    </Modal>
  );
}

function ApproveButton({ record, onDone }: { record: AdminSpeedRecord; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  async function go() {
    if (busy) return;
    setBusy(true);
    try {
      const res = await write((key) => sendApproveRecord(key, record.id));
      if (!res.ok) {
        if (!authFailure(res.error)) toast("Không duyệt được", errorText(res.error));
        return;
      }
      toast("Đã duyệt số đo", `${record.speed_kmh} km/h · ${record.member_name}`);
      onDone();
    } finally {
      setBusy(false);
    }
  }
  return (
    <button type="button" onClick={() => void go()} disabled={busy} className={btnPrimaryCls}>
      {busy ? "Đang duyệt…" : "Duyệt"}
    </button>
  );
}

const REASON_MAX = 200;

/** Từ chối số đo hội viên gửi: lý do bắt buộc (≤ 200 ký tự), hội viên nhận thông báo kèm lý do. */
function RejectDialog({ record, onClose, onDone }: { record: AdminSpeedRecord; onClose: () => void; onDone: () => void }) {
  const id = useId();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const text = reason.trim();
  async function go() {
    setSubmitted(true);
    if (!text || busy) return;
    setBusy(true);
    setBanner("");
    try {
      const res = await write((key) => sendRejectRecord(key, record.id, text));
      if (!res.ok) {
        if (!authFailure(res.error)) setBanner(errorText(res.error));
        return;
      }
      toast("Đã từ chối số đo", `${record.speed_kmh} km/h · ${record.member_name}`);
      onDone();
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      open
      onClose={onClose}
      title="Từ chối số đo"
      footer={
        <>
          <button type="button" onClick={onClose} className={btnCls} disabled={busy}>
            Hủy
          </button>
          <button type="button" onClick={() => void go()} disabled={busy} className={btnDangerCls}>
            {busy ? "Đang gửi…" : "Từ chối"}
          </button>
        </>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      <p className="text-sm">
        Số đo <b>{record.speed_kmh} km/h</b> của {record.member_name}. Hội viên sẽ nhận thông báo kèm lý do.
      </p>
      <div>
        <label htmlFor={id} className="mb-1 block text-sm font-medium">
          Lý do <span className="text-danger">*</span>
        </label>
        <textarea id={id} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={REASON_MAX} rows={3} aria-invalid={(submitted && !text) || undefined} className={inputCls} />
        <p className="mt-1 flex justify-between text-xs text-muted">
          <span className={submitted && !text ? "text-danger" : ""}>{submitted && !text ? "Vui lòng nhập lý do." : ""}</span>
          <span className="tabular-nums">
            {reason.length}/{REASON_MAX}
          </span>
        </p>
      </div>
    </Modal>
  );
}

/** Xóa thật số đo nhập tay (không phải giao dịch tiền); server ghi lại nhật ký trước → sau. */
function DeleteDialog({ record, onClose, onDone }: { record: AdminSpeedRecord; onClose: () => void; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");
  async function go() {
    if (busy) return;
    setBusy(true);
    setBanner("");
    try {
      const res = await write((key) => sendAdminDeleteRecord(key, record.id));
      if (!res.ok) {
        if (!authFailure(res.error)) setBanner(errorText(res.error));
        return;
      }
      toast("Đã xóa số đo", `${record.speed_kmh} km/h · ${record.member_name}`);
      onDone();
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      open
      onClose={onClose}
      title="Xóa số đo?"
      footer={
        <>
          <button type="button" onClick={onClose} className={btnCls} disabled={busy}>
            Hủy
          </button>
          <button type="button" onClick={() => void go()} disabled={busy} className={btnDangerCls}>
            {busy ? "Đang xóa…" : "Xóa số đo"}
          </button>
        </>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      <p className="text-sm">
        Xóa số đo <b>{record.speed_kmh} km/h</b> của {record.member_name}
        {record.video ? " cùng video đã gắn" : ""}. Bảng xếp hạng và kỷ lục sẽ được tính lại. Không hoàn tác được.
      </p>
    </Modal>
  );
}
