"use client";

import { useEffect, useId, useState } from "react";
import { authFailure } from "@/components/booking-engine/booking-dialogs";
import { CustomerPicker, type CustomerState, emptyCustomer } from "@/components/booking-engine/customer-picker";
import { btnCls, btnPrimaryCls, ErrorBanner, inputCls } from "@/components/booking-engine/ui";
import { Modal } from "@/components/ui/modal";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { addDaysIso, todayVn, vnDate, vnIso } from "@/lib/format";
import { parseVideoUrl, VIDEO_LINK_HINT } from "@/lib/video";
import { type AdminRecordRow, getAdminCourts, type RecordInput, sendAdminCreateRecord, sendAdminUpdateRecord, sendMemberSubmitRecord } from "./requests";
import { VideoPlayer } from "./video-player";

// Hộp nhập số đo (T-047): Admin thêm / sửa, hội viên gửi cú đập (chờ duyệt). Giờ nhập theo múi giờ Việt Nam.

export type RecordFormMode = { kind: "admin-create" } | { kind: "admin-edit"; record: AdminRecordRow } | { kind: "member-submit" };

const MIN = 50;
const MAX = 500;

const nowHm = () => new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Ho_Chi_Minh" }).format(new Date());
const hmOf = (iso: string) => new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Ho_Chi_Minh" }).format(new Date(iso));

type Court = { code: string; name: string; is_active?: boolean };

/** `courts`: danh sách sân do nơi gọi cấp (hội viên: từ /mine); bỏ trống (Admin) thì lấy từ API sân của Admin. */
export function RecordFormDialog({ mode, courts: given, dailyLimit = 5, onClose, onDone }: { mode: RecordFormMode; courts?: Court[]; dailyLimit?: number; onClose: () => void; onDone: () => void }) {
  const editing = mode.kind === "admin-edit" ? mode.record : null;
  const id = useId();
  const [customer, setCustomer] = useState<CustomerState>(emptyCustomer);
  const [speed, setSpeed] = useState(editing ? String(editing.speed_kmh) : "");
  const [date, setDate] = useState(editing ? vnDate(editing.measured_at) : todayVn());
  const [time, setTime] = useState(editing ? hmOf(editing.measured_at) : nowHm());
  const [court, setCourt] = useState(editing?.resource_code ?? "");
  const [url, setUrl] = useState(editing?.video?.url ?? "");
  const [fetched, setFetched] = useState<Court[]>([]);
  const courts = given ?? fetched;
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");
  const [submitted, setSubmitted] = useState(false);

  // Admin: danh mục sân thật (gồm sân ngừng); hội viên không có quyền này nên nhận danh sách từ /mine
  useEffect(() => {
    if (given) return;
    let live = true;
    void getAdminCourts().then((res) => {
      if (!live || !res.ok) return;
      setFetched(res.data);
    });
    return () => {
      live = false;
    };
  }, [given]);

  // Dòng cũ chỉ có tên sân: chọn lại theo tên khi đã có danh sách
  const courtValue = court || (editing?.resource_name ? (courts.find((c) => c.name === editing.resource_name)?.code ?? "") : "");

  const parsed = parseVideoUrl(url);
  const speedNum = Number(speed);
  const errors = {
    pick: mode.kind === "admin-create" && !customer.picked ? "Vui lòng chọn một hội viên." : "",
    speed: speed.trim() === "" ? "Vui lòng nhập tốc độ." : !Number.isInteger(speedNum) || speedNum < MIN || speedNum > MAX ? `Tốc độ là số nguyên từ ${MIN} đến ${MAX} km/h.` : "",
    when: !date || !time ? "Vui lòng chọn ngày và giờ." : vnIso(date, time) > vnIso(todayVn(), nowHm()) ? "Thời điểm không được ở tương lai." : date < addDaysIso(todayVn(), -365) ? "Chỉ nhận số đo trong 365 ngày gần đây." : "",
    video: url.trim() !== "" && !parsed ? VIDEO_LINK_HINT : "",
  };
  const invalid = Object.values(errors).some(Boolean);

  async function save() {
    setSubmitted(true);
    if (invalid || busy) return;
    setBusy(true);
    setBanner("");
    const body: RecordInput = { speed_kmh: speedNum, measured_at: vnIso(date, time), resource_code: courtValue || null, video_url: url.trim() || null };
    try {
      const res = await write<unknown>((key) => {
        if (mode.kind === "admin-create") return sendAdminCreateRecord(key, { ...body, member_code: customer.picked!.member_code });
        if (mode.kind === "admin-edit") return sendAdminUpdateRecord(key, mode.record.id, { ...body, version: mode.record.version });
        return sendMemberSubmitRecord(key, body);
        // Hết lượt trong ngày: báo ngay, không tự thử lại (Retry-After kéo dài tới 0h hôm sau)
      }, { retryRateLimit: false });
      if (!res.ok) {
        if (res.error.code === "E-SEC-5") setBanner(`Hôm nay bạn đã gửi đủ ${dailyLimit} lượt, thử lại sau 0h.`);
        else if (!authFailure(res.error)) setBanner(errorText(res.error));
        return;
      }
      if (mode.kind === "member-submit") toast("Đã gửi cú đập", "Admin sẽ duyệt trước khi tính vào bảng xếp hạng.");
      else toast(mode.kind === "admin-create" ? "Đã thêm số đo" : "Đã lưu số đo", `${speedNum} km/h`);
      onDone();
    } finally {
      setBusy(false);
    }
  }

  const title = mode.kind === "admin-create" ? "Thêm số đo" : mode.kind === "admin-edit" ? "Sửa số đo" : "Gửi cú đập";
  const show = (m: string) => (submitted && m ? <p className="mt-1 text-xs text-danger">{m}</p> : null);
  return (
    <Modal
      open
      onClose={onClose}
      size="wide"
      title={title}
      footer={
        <>
          <button type="button" onClick={onClose} className={btnCls} disabled={busy}>
            Hủy
          </button>
          <button type="button" onClick={() => void save()} disabled={busy} className={btnPrimaryCls}>
            {busy ? "Đang lưu…" : mode.kind === "member-submit" ? "Gửi" : "Lưu"}
          </button>
        </>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      {mode.kind === "member-submit" ? <p className="text-sm text-muted">Số đo của bạn sẽ chờ Admin duyệt rồi mới tính vào bảng xếp hạng. Mỗi ngày gửi tối đa {dailyLimit} lượt.</p> : null}
      {editing ? (
        <p className="text-sm">
          {editing.member_name}
          {editing.member_code ? ` (${editing.member_code})` : ""}
        </p>
      ) : null}
      {mode.kind === "admin-create" ? <CustomerPicker state={customer} onChange={setCustomer} submitted={submitted} memberOnly /> : null}

      <div className="grid gap-3 sm:grid-cols-2">
        <div>
          <label htmlFor={`${id}-speed`} className="mb-1 block text-sm font-medium">
            Tốc độ (km/h) <span className="text-danger">*</span>
          </label>
          <input id={`${id}-speed`} type="number" inputMode="numeric" min={MIN} max={MAX} step={1} value={speed} onChange={(e) => setSpeed(e.target.value)} aria-invalid={(submitted && !!errors.speed) || undefined} className={`${inputCls} h-11 tabular-nums`} />
          {show(errors.speed)}
        </div>
        <div>
          <label htmlFor={`${id}-court`} className="mb-1 block text-sm font-medium">
            Sân (không bắt buộc)
          </label>
          <select id={`${id}-court`} value={courtValue} onChange={(e) => setCourt(e.target.value)} className={`${inputCls} h-11`}>
            <option value="">Không chọn sân</option>
            {courts.map((c) => (
              <option key={c.code} value={c.code}>
                {c.name}
                {c.is_active === false ? " (ngừng hoạt động)" : ""}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor={`${id}-date`} className="mb-1 block text-sm font-medium">
            Ngày đo <span className="text-danger">*</span>
          </label>
          <input id={`${id}-date`} type="date" value={date} min={addDaysIso(todayVn(), -365)} max={todayVn()} onChange={(e) => setDate(e.target.value)} aria-invalid={(submitted && !!errors.when) || undefined} className={`${inputCls} h-11`} />
        </div>
        <div>
          <label htmlFor={`${id}-time`} className="mb-1 block text-sm font-medium">
            Giờ đo <span className="text-danger">*</span>
          </label>
          <input id={`${id}-time`} type="time" value={time} onChange={(e) => setTime(e.target.value)} aria-invalid={(submitted && !!errors.when) || undefined} className={`${inputCls} h-11`} />
        </div>
      </div>
      {show(errors.when)}

      <div>
        <label htmlFor={`${id}-video`} className="mb-1 block text-sm font-medium">
          Link video (không bắt buộc)
        </label>
        <input
          id={`${id}-video`}
          type="url"
          inputMode="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://www.youtube.com/watch?v=…  hoặc  https://…/clip.mp4"
          aria-invalid={!!errors.video || undefined}
          aria-describedby={`${id}-vhint`}
          autoComplete="off"
          className={`${inputCls} h-11 ${errors.video ? "border-danger" : ""}`}
        />
        <p id={`${id}-vhint`} className={`mt-1 text-xs ${errors.video ? "text-danger" : "text-muted"}`} role={errors.video ? "alert" : undefined}>
          {VIDEO_LINK_HINT}
        </p>
      </div>
      {parsed ? (
        <div>
          <p className="mb-1 text-xs font-semibold text-muted">Xem thử</p>
          <VideoPlayer key={parsed.url} video={parsed} title="Xem thử video số đo" />
        </div>
      ) : null}
    </Modal>
  );
}
