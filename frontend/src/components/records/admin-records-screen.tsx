"use client";

import { useCallback, useEffect, useId, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { authFailure } from "@/components/booking-engine/booking-dialogs";
import { btnCls, btnDangerCls, btnPrimaryCls, ErrorBanner, inputCls } from "@/components/booking-engine/ui";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatDate, formatTime } from "@/lib/format";
import { parseVideoUrl, VIDEO_LINK_HINT } from "@/lib/video";
import { type AdminRecordRow as AdminSpeedRecord, type AdminSpeedRecordList, getAdminSpeedRecords, SOURCE_LABEL, sendAdminDeleteRecord, sendApproveRecord, sendRecordVideo, sendRejectRecord, sendRemoveRecordVideo } from "./requests";
import { RecordFormDialog, type RecordFormMode } from "./record-form-dialog";
import { VideoPlayer } from "./video-player";

// /admin/ky-luc (T-046 + T-047, chỉ Admin): số đo mới nhất trước, lọc Có video / Chưa có, gắn / sửa / gỡ video bằng cách dán link (có xem thử);
// thêm / sửa / xóa số đo nhập tay (trừ nguồn máy đo); tab "Chờ duyệt" để duyệt / từ chối số đo hội viên gửi.

const SIZE = 20;
const FILTERS = [
  { key: "all", label: "Tất cả" },
  { key: "yes", label: "Có video" },
  { key: "no", label: "Chưa có video" },
] as const;
type Filter = (typeof FILTERS)[number]["key"];
type Tab = "all" | "pending";

export function AdminRecordsScreen() {
  const [tab, setTab] = useState<Tab>("all");
  const [filter, setFilter] = useState<Filter>("all");
  const [pending, setPending] = useState(0);
  const [form, setForm] = useState<RecordFormMode | null>(null);
  const [del, setDel] = useState<AdminSpeedRecord | null>(null);
  const [reject, setReject] = useState<AdminSpeedRecord | null>(null);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<AdminSpeedRecordList | null>(null);
  const [error, setError] = useState("");
  const [edit, setEdit] = useState<AdminSpeedRecord | null>(null);
  const [remove, setRemove] = useState<AdminSpeedRecord | null>(null);

  const load = useCallback(async () => {
    const res = await getAdminSpeedRecords(tab === "pending" ? { status: "pending", page, size: SIZE } : { has_video: filter === "all" ? undefined : filter === "yes", page, size: SIZE });
    if (res.ok) {
      setPending(res.data.pending_count); // không phụ thuộc bộ lọc
      setData(res.data);
      setError("");
    } else if (!authFailure(res.error)) setError(errorText(res.error));
  }, [tab, filter, page]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải khi đổi bộ lọc / trang
    void load();
  }, [load]);

  const pages = data ? Math.max(1, Math.ceil(data.total / data.size)) : 1;
  const chip = (on: boolean) => `rounded-full border px-3 py-1.5 text-sm ${on ? "border-primary bg-primary text-white" : "border-border bg-surface hover:bg-primary-softer"}`;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold sm:text-2xl">Kỷ lục &amp; video</h1>
        <button type="button" onClick={() => setForm({ kind: "admin-create" })} className={btnPrimaryCls}>
          + Thêm số đo
        </button>
      </div>
      <p className="text-sm text-muted">Nhập số đo tốc độ, gắn link video (YouTube hoặc file .mp4 / .webm) để hội viên xem ở Tổng quan và Video &amp; kỷ lục. Số đo hội viên gửi nằm ở tab Chờ duyệt.</p>

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
        <p className="rounded-lg border border-border bg-surface p-8 text-center text-muted">{tab === "pending" ? "Không có số đo nào chờ duyệt." : filter === "all" ? "Chưa có số đo nào." : "Không có số đo nào khớp bộ lọc."}</p>
      ) : (
        <ul className="space-y-3">
          {data.items.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-3 rounded-xl border border-border bg-surface p-4 shadow-card">
              <div className="min-w-0">
                <p className="flex flex-wrap items-baseline gap-x-2">
                  <b className="text-xl tabular-nums">{r.speed_kmh} km/h</b>
                  {r.video ? <span className="rounded-full bg-primary-softer px-2 py-0.5 text-xs font-semibold text-primary">{r.video.kind === "youtube" ? "YouTube" : "File video"}</span> : <span className="rounded-full bg-background px-2 py-0.5 text-xs text-muted">Chưa có video</span>}
                  <span className="rounded-full border border-border px-2 py-0.5 text-xs text-muted">{SOURCE_LABEL[r.source]}</span>
                  {r.status === "pending" ? <span className="rounded-full bg-cta px-2 py-0.5 text-xs font-semibold text-cta-fg">Chờ duyệt</span> : null}
                  {r.status === "rejected" ? <span className="rounded-full bg-danger px-2 py-0.5 text-xs font-semibold text-white">Bị từ chối</span> : null}
                </p>
                <p className="text-sm font-medium">
                  {r.member_name}
                  {r.member_code ? <span className="ml-1.5 rounded bg-background px-1.5 py-0.5 font-mono text-xs font-normal text-muted">{r.member_code}</span> : null}
                </p>
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
                <button type="button" onClick={() => setEdit(r)} className={r.video || r.status === "pending" ? btnCls : btnPrimaryCls}>
                  {r.video ? "Sửa video" : "Gắn video"}
                </button>
                {r.video ? (
                  <button type="button" onClick={() => setRemove(r)} className={btnCls}>
                    Gỡ video
                  </button>
                ) : null}
                {r.editable ? (
                  <>
                    <button type="button" onClick={() => setForm({ kind: "admin-edit", record: r })} className={btnCls}>
                      Sửa số đo
                    </button>
                    <button type="button" onClick={() => setDel(r)} className={btnCls}>
                      Xóa
                    </button>
                  </>
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

      {edit ? (
        <VideoDialog
          key={edit.id}
          record={edit}
          onClose={() => setEdit(null)}
          onSaved={() => {
            setEdit(null);
            void load();
          }}
        />
      ) : null}
      {form ? (
        <RecordFormDialog
          mode={form}
          onClose={() => setForm(null)}
          onDone={() => {
            setForm(null);
            void load();
          }}
        />
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

/** Hộp gắn / sửa link: dán link → xem thử ngay trong hộp; link sai báo ngay, server (E-REC-1) kiểm lại. */
function VideoDialog({ record, onClose, onSaved }: { record: AdminSpeedRecord; onClose: () => void; onSaved: () => void }) {
  const id = useId();
  const [url, setUrl] = useState(record.video?.url ?? "");
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");
  const parsed = parseVideoUrl(url);
  const invalid = url.trim() !== "" && !parsed;
  const unchanged = url.trim() === (record.video?.url ?? "");

  async function save() {
    if (!parsed || busy) return;
    setBusy(true);
    setBanner("");
    try {
      const res = await write((key) => sendRecordVideo(key, record.id, url.trim()));
      if (!res.ok) {
        if (!authFailure(res.error)) setBanner(errorText(res.error));
        return;
      }
      toast(record.video ? "Đã cập nhật video" : "Đã gắn video", `${record.speed_kmh} km/h · ${record.member_name}`);
      onSaved();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      size="wide"
      title={record.video ? "Sửa video" : "Gắn video"}
      footer={
        <>
          <button type="button" onClick={onClose} className={btnCls} disabled={busy}>
            Hủy
          </button>
          <button type="button" onClick={() => void save()} disabled={!parsed || unchanged || busy} className={btnPrimaryCls}>
            {busy ? "Đang lưu…" : "Lưu"}
          </button>
        </>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      <p className="text-sm">
        <b className="tabular-nums">{record.speed_kmh} km/h</b> · {record.member_name}
        {record.member_code ? ` (${record.member_code})` : ""}
      </p>
      <div>
        <label htmlFor={id} className="mb-1 block text-sm font-medium">
          Link video
        </label>
        <input
          id={id}
          type="url"
          inputMode="url"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
            setBanner("");
          }}
          placeholder="https://www.youtube.com/watch?v=…  hoặc  https://…/clip.mp4"
          aria-invalid={invalid || undefined}
          aria-describedby={`${id}-hint`}
          className={`${inputCls} h-11 ${invalid ? "border-danger" : ""}`}
          autoComplete="off"
        />
        <p id={`${id}-hint`} className={`mt-1 text-xs ${invalid ? "text-danger" : "text-muted"}`} role={invalid ? "alert" : undefined}>
          {VIDEO_LINK_HINT}
        </p>
      </div>
      {parsed ? (
        <div>
          <p className="mb-1 text-xs font-semibold text-muted">Xem thử</p>
          {/* key theo link: đổi link thì dựng lại, không phát tiếp video cũ */}
          <VideoPlayer key={parsed.url} video={parsed} title={`Xem thử video ${record.speed_kmh} km/h`} />
        </div>
      ) : null}
    </Modal>
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
