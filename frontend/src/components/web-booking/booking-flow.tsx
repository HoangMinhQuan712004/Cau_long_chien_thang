"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { CourtGrid, type GridCell, type GridRow } from "@/components/court-grid/court-grid";
import { MyBookingModal } from "@/components/member-area/cell-dialogs";
import { getMemberCalendar } from "@/components/member-area/cell-requests";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import type { Dictionary } from "@/i18n/dictionaries";
import { otpErrorText, otpResendAt } from "@/lib/api/auth";
import { api } from "@/lib/api/client";
import { errorText, write } from "@/lib/api/write";
import { cn } from "@/lib/cn";
import { formatLongDate, formatVnd } from "@/lib/format";
import { fullAddress, phoneHref, site } from "@/lib/site";
import { isValidPhone, normalizePhone } from "@/lib/phone";
import { DayStrip } from "./day-strip";
import { EventDialog } from "./event-dialog";
import { MemberHint } from "./member-hint";
import { clearToken, readJson, removeKey, saveToken, savedToken, useVerifiedPhone, writeJson } from "./session-store";
import { toast } from "@/lib/feedback";
import { BookingPhoneOtp, type VerifiedAccount } from "./phone-otp";
import { getWebCalendar, requestBookingPhone, sendCheckout } from "./requests";
import { MAX_CELLS, RESTORE_KEY, type Cell, type SlotExtra, type WebCalendar } from "./types";

// /dat-san – bước 1: chọn khung giờ trên lưới (nhiều ô, nhiều sân, cùng 1 ngày, tối đa 16 ô); bước 2: nhập thông tin người đặt.
// Server tự tính giá và kiểm lại mọi điều kiện; FE chỉ gửi sân + giờ + thông tin khách (T-008 AC1–AC9).

const STORAGE_KEY = "wk-booking-v1";
type Me = { full_name: string; phone: string | null; phone_verified: boolean };

type Saved = { date: string; cells: Cell[]; name: string; phone: string; note: string; step: 1 | 2 };
type Restore = { date: string; items: Cell[] };

const cellKey = (c: Cell) => `${c.code}|${c.hour}`;
const pad2 = (n: number) => String(n).padStart(2, "0");
const range = (a: number, b: number) => `${pad2(a)}:00 – ${pad2(b)}:00`;

type Group = { code: string; name: string; hours: number[]; ranges: string; amount: number };

/** Gom ô đã chọn theo sân (đúng thứ tự sân trên lưới), nối giờ liền nhau: "17:00 – 18:00, 19:00 – 21:00". */
function summarize(calendar: WebCalendar, cells: Cell[], price: Map<string, number>): Group[] {
  const out: Group[] = [];
  for (const r of calendar.resources) {
    const hours = cells.filter((c) => c.code === r.code).map((c) => c.hour).sort((a, b) => a - b);
    if (!hours.length) continue;
    const parts: string[] = [];
    let start = hours[0];
    let prev = hours[0];
    for (const h of hours.slice(1)) {
      if (h === prev + 1) {
        prev = h;
        continue;
      }
      parts.push(range(start, prev + 1));
      start = prev = h;
    }
    parts.push(range(start, prev + 1));
    out.push({
      code: r.code,
      name: r.name,
      hours,
      ranges: parts.join(", "),
      amount: hours.reduce((s, h) => s + (price.get(`${r.code}|${h}`) ?? 0), 0),
    });
  }
  return out;
}

/** Đặt trong khu hội viên (T-018 AC4): họ tên + SĐT lấy từ hồ sơ, khóa; bỏ OTP; server nhận `as_member`. */
export type MemberIdentity = { name: string; phone: string };

type Props = {
  initialDate: string;
  today: string;
  hotline: string;
  texts: Dictionary["phoneVerify"];
  member?: MemberIdentity;
  /** `?event=` (T-023 AC18): tự mở popup sự kiện này khi vào trang */
  initialEvent?: string | null;
};

export function WebBookingFlow({ initialDate, today, hotline, texts, member, initialEvent = null }: Props) {
  const router = useRouter();
  // Phiên đặt trong khu hội viên lưu riêng, không lẫn với /dat-san công khai
  const storageKey = member ? `${STORAGE_KEY}:member` : STORAGE_KEY;
  const [date, setDate] = useState(initialDate);
  const [calendar, setCalendar] = useState<WebCalendar | null>(null);
  const [loadError, setLoadError] = useState("");
  const [cells, setCells] = useState<Cell[]>([]);
  const [step, setStep] = useState<1 | 2>(1);
  const [form, setForm] = useState({ name: member?.name ?? "", phone: member?.phone ?? "", note: "" });
  const [touched, setTouched] = useState<{ name?: boolean; phone?: boolean; note?: boolean }>({});
  const [submitted, setSubmitted] = useState(false);
  const [banner, setBanner] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [pendingDate, setPendingDate] = useState<string | null>(null);
  // Thanh tổng dưới đáy: mở rộng để xem danh sách khối đã chọn (T-028 AC7)
  const [barOpen, setBarOpen] = useState(false);
  // Hội viên bấm ô "Sân của bạn" / "Sự kiện" (T-023): hộp thoại tương ứng; `opener` để trả focus về ô khi đóng
  const [cellDialog, setCellDialog] = useState<{ kind: "mine" | "event"; code: string } | null>(initialEvent ? { kind: "event", code: initialEvent } : null);
  const openerRef = useRef<HTMLElement | null>(null);
  // Bước nhập OTP (đang mở khi != null); khách đăng nhập đã xác minh SĐT thì bỏ qua (AC26)
  const [otp, setOtp] = useState<{ phone: string; resendAt: number | null; testOtp: string | null } | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [isGuest, setIsGuest] = useState(false); // /auth/me trả 401 ⇒ chưa đăng nhập (hiện gợi ý hội viên)
  const verifiedPhone = useVerifiedPhone();
  const ids = { name: useId(), phone: useId(), note: useId() };

  const dateRef = useRef(initialDate);
  const cellsRef = useRef<Cell[]>([]);
  const stepRef = useRef<1 | 2>(1);
  const restoreRef = useRef<Restore | null>(null);
  const ready = useRef(false);

  const applyCells = useCallback((next: Cell[]) => {
    cellsRef.current = next;
    setCells(next);
  }, []);
  const applyStep = useCallback((next: 1 | 2) => {
    stepRef.current = next;
    setStep(next);
  }, []);

  /** Tải lịch; bỏ các ô đang chọn vừa bị người khác đặt (AC4); áp dụng "Đặt lại" ở lần tải đầu của ngày đó. */
  const load = useCallback(
    async (d: string, quiet = false) => {
      if (!quiet) setLoading(true);
      const res = await (member ? getMemberCalendar(d) : getWebCalendar(d));
      if (dateRef.current !== d) return;
      if (!quiet) setLoading(false);
      if (!res.ok) {
        if (!quiet) setLoadError(errorText(res.error));
        return;
      }
      const cal = res.data;
      setCalendar(cal);
      setLoadError("");

      const freeSet = new Set<string>();
      for (const r of cal.resources) {
        for (const s of r.slots) if (s.state === "free") freeSet.add(`${r.code}|${s.start_hour}`);
      }

      const restore = restoreRef.current;
      if (restore && restore.date === d) {
        restoreRef.current = null;
        const wanted = restore.items
          .filter((c) => freeSet.has(cellKey(c)))
          .slice(0, MAX_CELLS);
        if (wanted.length) {
          applyCells(wanted);
          setNotice(wanted.length === restore.items.length ? "" : "Một số khung đã có người đặt, đã bỏ khỏi lựa chọn.");
          return;
        }
      }

      const cur = cellsRef.current;
      const lost = cur.filter((c) => !freeSet.has(cellKey(c)));
      if (lost.length) {
        const nameOf = (code: string) => cal.resources.find((r) => r.code === code)?.name ?? code;
        const kept = cur.filter((c) => freeSet.has(cellKey(c)));
        applyCells(kept);
        setNotice(`Khung ${lost.map((c) => `${nameOf(c.code)} ${pad2(c.hour)}:00`).join(", ")} vừa có người đặt.`);
        if (!kept.length) applyStep(1);
      }
    },
    [applyCells, applyStep, member],
  );

  // Lần đầu: khôi phục lựa chọn đã lưu trong tab (F5 không mất – AC9) rồi tải lịch.
  useEffect(() => {
    const saved = readJson<Saved>(storageKey);
    if (saved && saved.date === initialDate) {
      /* eslint-disable react-hooks/set-state-in-effect -- khôi phục từ sessionStorage sau khi hydrate */
      applyCells(saved.cells ?? []);
      setForm({ name: member?.name ?? saved.name ?? "", phone: member?.phone ?? saved.phone ?? "", note: saved.note ?? "" });
      if (saved.step === 2 && (saved.cells?.length ?? 0) > 0) applyStep(2);
      /* eslint-enable react-hooks/set-state-in-effect */
    }
    const restore = readJson<Restore>(RESTORE_KEY);
    if (restore) {
      removeKey(RESTORE_KEY);
      if (restore.date === initialDate) restoreRef.current = restore;
    }
    ready.current = true;
    void load(initialDate);
  }, [initialDate, applyCells, applyStep, load, storageKey, member]);

  // Lưu lựa chọn + thông tin đã nhập vào sessionStorage của tab.
  useEffect(() => {
    if (!ready.current) return;
    writeJson(storageKey, { date, cells, name: form.name, phone: form.phone, note: form.note, step } satisfies Saved);
  }, [date, cells, form, step, storageKey]);

  // Tự tải lại mỗi 30 giây khi tab đang hiển thị, và ngay khi quay lại tab.
  useEffect(() => {
    const tick = () => {
      if (document.visibilityState === "visible") void load(dateRef.current, true);
    };
    const id = setInterval(tick, 30_000);
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [load]);

  // ---- Dữ liệu dẫn xuất ----
  const priceMap = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of calendar?.resources ?? []) for (const s of r.slots) if (s.state === "free" && s.price != null) m.set(`${r.code}|${s.start_hour}`, s.price);
    return m;
  }, [calendar]);
  const groups = useMemo(() => (calendar ? summarize(calendar, cells, priceMap) : []), [calendar, cells, priceMap]);
  const total = groups.reduce((s, g) => s + g.amount, 0);
  const totalHours = cells.length;
  const selected = useMemo(() => new Set(cells.map(cellKey)), [cells]);
  // Lưới dùng chung (T-025): dữ liệu lịch khách / hội viên → hàng + ô. Hội viên: ô của mình mở thông tin + hóa đơn, ô người khác chỉ báo đã có người đặt (T-023 AC1–AC3).
  const gridRows = useMemo<GridRow[]>(
    () =>
      (calendar?.resources ?? []).map((r) => {
        const byHour = new Map(r.slots.map((s) => [s.start_hour, s as (typeof r.slots)[number] & SlotExtra]));
        const out: Record<number, GridCell> = {};
        for (const h of calendar?.columns ?? []) {
          const s = byHour.get(h);
          const key = `${r.code}|${h}`;
          if (!s || s.state === "closed") out[h] = { kind: "off" };
          else if (s.state === "booked") {
            const orderCode = s.order_code;
            out[h] =
              member && s.mine && orderCode
                ? {
                    kind: "block",
                    key: `mine|${orderCode}`,
                    tone: "mine",
                    lines: ["Sân của bạn"],
                    aria: "sân của bạn, xem chi tiết",
                    onClick: (el) => {
                      openerRef.current = el;
                      setCellDialog({ kind: "mine", code: orderCode });
                    },
                  }
                : { kind: "block", key: "booked", tone: "booked", lines: ["Đã đặt"], aria: "đã có người đặt", onClick: () => toast("Khung giờ này đã có người đặt", undefined, "info") };
          } else if (s.state === "event") {
            const eventCode = s.event_code;
            out[h] = {
              kind: "block",
              key: `event|${eventCode ?? key}`,
              tone: "session",
              lines: [s.has_ticket ? "Có vé" : "Sự kiện", <b key="n" className="text-xs">{s.taken}/{s.capacity}</b>],
              aria: `sự kiện ${s.taken ?? 0} trên ${s.capacity ?? 0} người${s.has_ticket ? ", bạn đã có vé" : ""}${eventCode ? ", xem chi tiết" : ""}`,
              ring: Boolean(s.has_ticket),
              onClick: eventCode
                ? (el) => {
                    openerRef.current = el;
                    setCellDialog({ kind: "event", code: eventCode });
                  }
                : undefined,
            };
          } else out[h] = { kind: "free", price: s.price ?? null };
        }
        return { code: r.code, name: r.name, cells: out };
      }),
    [calendar, member],
  );
  const onlineOff = calendar ? !calendar.online_enabled : false;
  const holdMinutes = calendar?.hold_minutes ?? 5;

  function closeCellDialog() {
    setCellDialog(null);
    // Trả focus về ô đã bấm (hộp thoại gốc tự làm khi ô còn tồn tại; đây là dự phòng khi lưới vừa vẽ lại)
    // Mở từ `?event=`: bỏ tham số để F5 / chia sẻ link không mở lại popup
    if (window.location.search.includes("event=")) window.history.replaceState(null, "", `?ngay=${dateRef.current}`);
    const opener = openerRef.current;
    openerRef.current = null;
    if (opener) setTimeout(() => opener.isConnected && opener.focus(), 0);
  }

  // ---- Chọn ô / đổi ngày ----
  function toggle(code: string, hour: number) {
    if (loading) return;
    const cur = cellsRef.current;
    const k = `${code}|${hour}`;
    if (cur.some((c) => cellKey(c) === k)) {
      applyCells(cur.filter((c) => cellKey(c) !== k));
      setNotice("");
    } else if (cur.length >= MAX_CELLS) {
      setNotice(`Mỗi lần đặt tối đa ${MAX_CELLS} khung giờ.`);
    } else {
      applyCells([...cur, { code, hour }]);
      setNotice("");
    }
  }

  function applyDate(d: string) {
    dateRef.current = d;
    setDate(d);
    setCalendar(null);
    setLoadError("");
    applyCells([]);
    applyStep(1);
    setNotice("");
    setBanner("");
    window.history.replaceState(null, "", `?ngay=${d}`);
    void load(d);
  }

  function onDateInput(value: string) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value < today || value === dateRef.current) return;
    if (cellsRef.current.length) setPendingDate(value);
    else applyDate(value);
  }

  // Khách đang đăng nhập: điền sẵn tên + SĐT (không ghi đè nội dung đã nhập / khôi phục)
  useEffect(() => {
    api
      .GET("/api/v1/auth/me")
      .then(({ data }) => {
        if (!data) return setIsGuest(true);
        setIsGuest(false); // trang có thể được giữ lại (Activity) từ lúc chưa đăng nhập: bỏ cờ cũ
        setMe({ full_name: data.full_name, phone: data.phone ?? null, phone_verified: data.phone_verified });
        setForm((f) => ({ ...f, name: f.name || data.full_name, phone: f.phone || data.phone || "" }));
      })
      .catch(() => {});
  }, []);

  // Đặt online lúc đã đăng nhập: xác minh SĐT xong có thể thành hội viên / gộp tài khoản (T-021). Việc đặt sân vẫn tiếp tục.
  function afterAccountVerified(a: VerifiedAccount) {
    if (a.becameMember) toast(a.memberCode ? `Bạn đã là hội viên ${a.memberCode}` : "Bạn đã là hội viên", "Mục \"Khu hội viên\" đã có ở menu tài khoản.");
    else if (a.reason === "E-AUTH-31") toast("Tài khoản hội viên đang bị ngừng. Vui lòng liên hệ quầy.", undefined, "error");
    // Gộp tài khoản: cookie đã đổi ⇒ lấy lại thông tin tài khoản
    if (a.merged) {
      void api
        .GET("/api/v1/auth/me")
        .then(({ data }) => data && setMe({ full_name: data.full_name, phone: data.phone ?? null, phone_verified: data.phone_verified }))
        .catch(() => {});
    }
    // Header (menu "Khu hội viên") là server component ⇒ làm mới
    if (a.becameMember || a.merged) router.refresh();
  }

  // ---- Bước 2: kiểm tra + gửi ----
  const cleanName = form.name.trim().replace(/\s+/g, " ");
  const phone = normalizePhone(form.phone);
  const errors = {
    name: !cleanName ? "Vui lòng nhập họ tên." : cleanName.length > 100 ? "Họ tên tối đa 100 ký tự." : "",
    phone: !isValidPhone(phone) ? "Số điện thoại không hợp lệ — cần đủ 10 số." : "",
    note: form.note.trim().length > 200 ? "Ghi chú tối đa 200 ký tự." : "",
  };

  const skipOtp = Boolean(member) || Boolean(me?.phone_verified && me.phone && normalizePhone(me.phone) === phone);

  /** Bấm nút chính: kiểm form → (cần thì) gửi mã OTP → khi có phone_token mới tạo checkout. */
  async function submit(tokenOverride?: string) {
    setSubmitted(true);
    setBanner("");
    if (errors.name || errors.phone || errors.note || !calendar || !cells.length) {
      const first = errors.name ? ids.name : errors.phone ? ids.phone : errors.note ? ids.note : null;
      if (first) document.getElementById(first)?.focus();
      return;
    }
    const order = new Map(calendar.resources.map((r, i) => [r.code, i]));
    const slots = [...cells]
      .sort((a, b) => (order.get(a.code) ?? 0) - (order.get(b.code) ?? 0) || a.hour - b.hour)
      .map((c) => ({ resource_code: c.code, start_hour: c.hour }));
    const note = form.note.trim();
    const phoneToken = skipOtp ? null : (tokenOverride ?? savedToken(phone));
    if (!skipOtp && !phoneToken) {
      setBusy(true);
      try {
        const sent = await requestBookingPhone(phone);
        const at = otpResendAt(sent);
        // 429 vẫn sang bước nhập mã (mã trước còn dùng được); lỗi khác ⇒ báo ngay
        if (at === null) {
          if (!sent.ok) {
            setBanner(otpErrorText(texts.errors, sent));
            if (sent.code === "E-WEB-5") void load(dateRef.current, true);
          }
          return;
        }
        setOtp({ phone, resendAt: at, testOtp: sent.ok ? (sent.test_otp ?? null) : null });
      } finally {
        setBusy(false);
      }
      return;
    }
    setBusy(true);
    try {
      // Giới hạn 6 lượt tạo / 10 phút / IP: báo ngay khi bị chặn, không tự gửi lại (mỗi lần gửi lại cũng bị tính)
      const res = await write(
        (key) => sendCheckout(key, { date, slots, full_name: cleanName, phone, as_member: Boolean(member), ...(note ? { note } : {}), ...(phoneToken ? { phone_token: phoneToken } : {}) }),
        { retryRateLimit: false },
      );
      if (res.ok) {
        const token = res.data.token;
        if (!token) {
          setBanner("Không nhận được mã thanh toán. Vui lòng thử lại.");
          return;
        }
        removeKey(storageKey);
        router.push(member ? `/hoi-vien/thanh-toan/${token}` : `/thanh-toan/${token}`);
        return;
      }
      const e = res.error;
      if (e.code === "E-WEB-3" || e.code === "E-WEB-2") {
        // Trùng khung / khung không còn đặt được: về lưới, bỏ ô xung đột, tải lại lịch.
        const conflicts = Array.isArray(e.extra.conflicts) ? (e.extra.conflicts as { resource_code: string; start_hour: number }[]) : [];
        if (conflicts.length) applyCells(cellsRef.current.filter((c) => !conflicts.some((x) => x.resource_code === c.code && x.start_hour === c.hour)));
        setNotice(errorText(e));
        if (!cellsRef.current.length || conflicts.length) applyStep(1);
        void load(dateRef.current, true);
        return;
      }
      if (e.code === "E-WEB-5") void load(dateRef.current, true);
      if (e.code === "E-WEB-8") clearToken(); // token hết hạn / không khớp SĐT ⇒ xác minh lại ở lần bấm kế tiếp
      setBanner(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const field = "w-full rounded-lg border bg-surface px-3 py-2.5 text-sm";
  const showErr = (k: "name" | "phone" | "note") => (submitted || touched[k]) && errors[k];

  // ================= Bước 2 =================
  if (step === 2 && calendar) {
    return (
      <div className="mx-auto w-full max-w-xl space-y-5">
        <button type="button" onClick={() => applyStep(1)} className="text-sm text-muted hover:text-foreground">
          ← Quay lại chọn giờ
        </button>
        <div>
          <h2 className="text-2xl font-bold">Xác nhận đặt sân</h2>
          <p className="text-sm text-muted">Kiểm tra lại thông tin rồi thanh toán để giữ chỗ.</p>
        </div>

        <section className="rounded-xl bg-surface p-4 shadow-card sm:p-5" aria-labelledby="venue-title">
          <h3 id="venue-title" className="text-sm font-bold text-primary">
            Thông tin sân
          </h3>
          <p className="mt-2 font-semibold">{site.name}</p>
          <p className="text-sm text-muted">{fullAddress}</p>
          <a href={phoneHref} className="mt-1 inline-flex min-h-11 items-center text-sm font-semibold text-primary hover:underline focus-ring">
            {site.phone}
          </a>
        </section>

        <section className="rounded-xl bg-surface p-4 shadow-card sm:p-5" aria-labelledby="sum-title">
          <h3 id="sum-title" className="text-sm font-bold text-primary">
            Thông tin lịch đặt
          </h3>
          <dl className="mt-3 space-y-3 text-sm">
            {groups.map((g) => (
              <div key={g.code} className="grid grid-cols-[6.5rem_1fr] gap-x-3 gap-y-1">
                <dt className="text-muted">Sân</dt>
                <dd className="font-medium">{g.name}</dd>
                <dt className="text-muted">Khung giờ</dt>
                <dd className="font-medium">{g.ranges} ({g.hours.length} giờ)</dd>
                {groups.length > 1 ? (
                  <>
                    <dt className="text-muted">Tiền sân</dt>
                    <dd className="font-medium tabular-nums">{formatVnd(g.amount)}</dd>
                  </>
                ) : null}
              </div>
            ))}
            <div className="grid grid-cols-[6.5rem_1fr] gap-x-3 border-t border-border pt-3">
              <dt className="text-muted">Ngày</dt>
              <dd className="font-medium">{formatLongDate(date)}</dd>
              <dt className="text-muted">Tổng giờ</dt>
              <dd className="font-medium">{totalHours} giờ</dd>
            </div>
          </dl>
          <div className="mt-4 flex items-baseline justify-between border-t border-border pt-3">
            <span className="text-sm text-muted">Tổng tiền</span>
            <span className="text-xl font-bold tabular-nums">{formatVnd(total)}</span>
          </div>
        </section>

        {isGuest && !member ? <MemberHint next={`/dat-san?ngay=${date}`} /> : null}

        <section className="rounded-xl bg-surface p-4 shadow-card sm:p-5">
          <h3 className="text-sm font-bold text-primary">Khách hàng</h3>
          <div className="mt-3 space-y-4">
            <div>
              <label htmlFor={ids.name} className="mb-1 block text-sm font-medium">
                Họ tên <span className="text-danger">*</span>
              </label>
              <input
                id={ids.name}
                value={form.name}
                maxLength={120}
                readOnly={otp !== null || Boolean(member)}
                autoComplete="name"
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                onBlur={() => setTouched((t) => ({ ...t, name: true }))}
                aria-invalid={Boolean(showErr("name")) || undefined}
                aria-describedby={showErr("name") ? `${ids.name}-err` : undefined}
                className={`${field} ${showErr("name") ? "border-danger" : "border-border"}`}
              />
              {showErr("name") ? (
                <p id={`${ids.name}-err`} role="alert" className="mt-1 text-xs text-danger">
                  {errors.name}
                </p>
              ) : null}
            </div>
            <div>
              <label htmlFor={ids.phone} className="mb-1 block text-sm font-medium">
                Số điện thoại <span className="text-danger">*</span>
              </label>
              <input
                id={ids.phone}
                value={form.phone}
                inputMode="tel"
                autoComplete="tel"
                maxLength={16}
                readOnly={otp !== null || Boolean(member)}
                onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
                onBlur={() => setTouched((t) => ({ ...t, phone: true }))}
                aria-invalid={Boolean(showErr("phone")) || undefined}
                aria-describedby={`${ids.phone}-hint`}
                className={`${field} ${showErr("phone") ? "border-danger" : "border-border"}`}
              />
              {showErr("phone") ? (
                <p role="alert" className="mt-1 text-xs text-danger">
                  {errors.phone}
                </p>
              ) : null}
              <p id={`${ids.phone}-hint`} className="mt-1 text-xs text-muted">
                Dùng số này cùng mã booking để tra cứu.
                {isValidPhone(phone) && (skipOtp || verifiedPhone === phone) ? <b className="ml-1 font-semibold text-primary">Số điện thoại đã xác minh.</b> : null}
              </p>
            </div>
            <div>
              <label htmlFor={ids.note} className="mb-1 block text-sm font-medium">
                Ghi chú (không bắt buộc)
              </label>
              <textarea
                id={ids.note}
                value={form.note}
                placeholder="Ví dụ: cần mượn vợt"
                onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))}
                onBlur={() => setTouched((t) => ({ ...t, note: true }))}
                aria-invalid={Boolean(showErr("note")) || undefined}
                className={`${field} min-h-20 ${showErr("note") ? "border-danger" : "border-border"}`}
              />
              {showErr("note") ? <p className="mt-1 text-xs text-danger">{errors.note}</p> : null}
            </div>
          </div>

          {banner ? (
            <p role="alert" className="mt-4 rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
              {banner}
            </p>
          ) : null}
          {otp ? (
            <BookingPhoneOtp
              t={texts}
              phone={otp.phone}
              initialResendAt={otp.resendAt}
              initialTestOtp={otp.testOtp}
              onChangePhone={() => setOtp(null)}
              onVerified={(token, expiresAt, accountVerified, account) => {
                saveToken({ phone: otp.phone, token, expiresAt });
                // BE đã đánh dấu SĐT của tài khoản là đã xác minh ⇒ lần đặt sau bỏ OTP (AC40)
                if (accountVerified && me?.phone && normalizePhone(me.phone) === otp.phone) setMe({ ...me, phone_verified: true });
                afterAccountVerified(account);
                setOtp(null);
                void submit(token); // đã xác minh: giữ chỗ + tạo thanh toán luôn
              }}
            />
          ) : (
            <button
              type="button"
              onClick={() => void submit()}
              disabled={busy || onlineOff}
              className="mt-5 h-12 w-full rounded-lg bg-cta px-4 text-sm font-bold tracking-wide text-cta-fg uppercase hover:bg-cta-hover focus-ring disabled:opacity-60"
            >
              {busy ? "Đang xử lý…" : skipOtp || (isValidPhone(phone) && verifiedPhone === phone) ? "Xác nhận & thanh toán" : "Gửi mã xác minh"}
            </button>
          )}
          <p className="mt-2 text-center text-xs text-muted">Khung giờ được giữ {holdMinutes} phút để thanh toán, bắt đầu sau khi bạn xác minh số điện thoại.</p>
          {onlineOff ? (
            <p className="mt-2 text-center text-xs text-danger">Đặt online đang tạm ngưng. Vui lòng gọi hotline {hotline}.</p>
          ) : null}
        </section>

        <section className="rounded-xl border border-accent/50 bg-accent-soft p-4 text-sm sm:p-5" aria-labelledby="note-title">
          <h3 id="note-title" className="text-sm font-bold text-accent-fg">
            Lưu ý
          </h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-foreground">
            <li>Khung giờ được giữ {holdMinutes} phút để chuyển khoản; hết thời gian mà chưa nhận được tiền thì khung giờ được mở lại.</li>
            <li>Đặt sân online không hủy và không hoàn tiền.</li>
            <li>Vui lòng đến trước giờ chơi và báo mã booking tại quầy.</li>
          </ul>
        </section>
      </div>
    );
  }

  // ================= Bước 1 =================
  const hours = calendar?.columns ?? [];
  const openText =
    calendar && calendar.columns.length ? `Mở cửa ${pad2(calendar.columns[0])}:00 – ${pad2(calendar.columns[calendar.columns.length - 1] + 1)}:00 · ` : "";

  return (
    <div className={cn("space-y-4", cells.length > 0 && "pb-28 sm:pb-0")}>
      <DayStrip date={date} today={today} onPick={onDateInput} />

      <ul aria-label="Chú thích màu" className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted">
        <Legend swatch="border border-border-strong bg-surface" text="Trống" />
        <Legend swatch="bg-cell-booked" text="Đã đặt" />
        {member ? <Legend swatch="bg-blk-mine" text="Sân của bạn" /> : null}
        <Legend swatch="bg-blk-session" text="Sự kiện" />
        <Legend swatch="bg-cell-off" text="Không bán / Quá giờ" />
        <Legend swatch="border-2 border-sel-edge bg-sel" text="Đang chọn" />
      </ul>

      <p className="px-1 text-xs text-muted">
        {openText}Bấm vào ô trắng để chọn, có thể chọn nhiều khung giờ và nhiều sân trong cùng ngày. Đặt online thanh toán trước bằng chuyển khoản QR.
      </p>

      <section aria-label="Lịch sân" className="space-y-3">
        {loadError ? (
          <div role="alert" className="space-y-2 rounded-xl bg-surface py-8 text-center text-sm shadow-card">
            <p className="text-danger">{loadError}</p>
            <button type="button" onClick={() => void load(date)} className="min-h-11 rounded-lg border border-border px-4 py-2">
              Thử lại
            </button>
          </div>
        ) : !calendar ? (
          <p className="rounded-xl bg-surface py-10 text-center text-sm text-muted shadow-card">Đang tải lịch sân…</p>
        ) : calendar.resources.length === 0 ? (
          <p className="rounded-xl bg-surface py-10 text-center text-sm text-muted shadow-card">Chưa có sân nào mở cho ngày này.</p>
        ) : (
          <CourtGrid
            label="Lịch sân"
            columns={hours}
            rows={gridRows}
            selected={selected}
            selectable
            busy={loading}
            onToggle={toggle}
            onClear={() => applyCells([])}
            mergeBlocks
            scrollToNow={date === today}
            scrollKey={`${date}|${calendar.resources.length}`}
          />
        )}
        {onlineOff ? (
          <p role="status" className="rounded-lg border border-danger/40 bg-danger/10 p-3 text-sm text-danger">
            Đặt online đang tạm ngưng. Vui lòng gọi hotline {hotline}.
          </p>
        ) : null}
      </section>

      {notice ? (
        <p role="status" className="rounded-lg border border-border bg-surface p-3 text-sm">
          {notice}
        </p>
      ) : null}

      {cells.length > 0 ? (
        <section
          data-bottom-bar
          aria-label="Bạn đang chọn"
          className="fixed inset-x-0 bottom-0 z-40 rounded-t-[20px] bg-appbar text-surface shadow-[0_-6px_24px_rgb(0_0_0/0.25)] sm:sticky sm:bottom-3 sm:rounded-2xl sm:shadow-lg"
        >
          <div className="px-4 pt-2 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:py-3">
            <button
              type="button"
              onClick={() => setBarOpen((o) => !o)}
              aria-expanded={barOpen}
              aria-controls="bar-list"
              className="mx-auto mb-1 flex h-6 w-full items-center justify-center rounded text-surface/80 hover:text-surface focus-ring"
            >
              <span className="sr-only">{barOpen ? "Thu gọn danh sách khung đã chọn" : "Xem danh sách khung đã chọn"}</span>
              <svg aria-hidden viewBox="0 0 20 20" className={cn("size-5 transition-transform motion-reduce:transition-none", barOpen && "rotate-180")} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="m5 12.5 5-5 5 5" />
              </svg>
            </button>
            {barOpen ? (
              <ul id="bar-list" className="mb-3 max-h-40 space-y-1 overflow-y-auto rounded-xl bg-surface/10 p-3 text-sm">
                {groups.map((g) => (
                  <li key={g.code} className="flex items-baseline justify-between gap-3">
                    <span className="min-w-0">
                      <b>{g.name}</b>: {g.ranges}
                    </span>
                    <span className="shrink-0 tabular-nums">{formatVnd(g.amount)}</span>
                  </li>
                ))}
                <li className="pt-1 text-xs text-surface/80">Khung giờ được giữ {holdMinutes} phút sau khi bạn bấm thanh toán.</li>
              </ul>
            ) : null}
            <div className="flex items-center gap-3">
              <div className="min-w-0 flex-1 leading-tight">
                <p className="text-xs text-surface/80">
                  Tổng giờ: <b className="text-surface">{totalHours}</b>
                </p>
                <p className="text-lg font-bold tabular-nums">
                  <span className="text-xs font-normal text-surface/80">Tổng tiền: </span>
                  {formatVnd(total)}
                </p>
              </div>
              <Button variant="cta" onClick={() => applyStep(2)} disabled={onlineOff || !calendar} className="h-12 min-w-36 px-6 text-sm sm:h-12 sm:text-sm">
                Tiếp theo
              </Button>
            </div>
          </div>
        </section>
      ) : null}

      {member ? <MyBookingModal orderCode={cellDialog?.kind === "mine" ? cellDialog.code : null} onClose={closeCellDialog} /> : null}
      <EventDialog
        eventCode={cellDialog?.kind === "event" ? cellDialog.code : null}
        date={date}
        member={member}
        hotline={hotline}
        texts={texts}
        onClose={closeCellDialog}
        onChanged={() => void load(dateRef.current, true)}
      />

      <Modal
        open={pendingDate !== null}
        onClose={() => setPendingDate(null)}
        title="Đổi ngày?"
        footer={
          <>
            <button type="button" onClick={() => setPendingDate(null)} className="rounded-md border border-border px-4 py-2 text-sm">
              Giữ ngày hiện tại
            </button>
            <button
              type="button"
              onClick={() => {
                const d = pendingDate;
                setPendingDate(null);
                if (d) applyDate(d);
              }}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white"
            >
              Đổi ngày
            </button>
          </>
        }
      >
        <p className="text-sm">Đổi ngày sẽ bỏ các khung giờ bạn đã chọn. Tiếp tục?</p>
      </Modal>
    </div>
  );
}

function Legend({ swatch, text }: { swatch: string; text: string }) {
  return (
    <li className="inline-flex items-center gap-1.5">
      <span aria-hidden className={`inline-block size-4 shrink-0 rounded-[5px] ${swatch}`} />
      {text}
    </li>
  );
}
