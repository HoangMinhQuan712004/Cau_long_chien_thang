"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Modal } from "@/components/ui/modal";
import type { Dictionary } from "@/i18n/dictionaries";
import { otpErrorText, otpResendAt } from "@/lib/api/auth";
import { api } from "@/lib/api/client";
import { errorText, write } from "@/lib/api/write";
import { formatLongDate, formatVnd } from "@/lib/format";
import { isValidPhone, normalizePhone } from "@/lib/phone";
import { MemberHint } from "./member-hint";
import { BookingPhoneOtp } from "./phone-otp";
import { getWebCalendar, requestBookingPhone, sendCheckout } from "./requests";
import { MAX_CELLS, RESTORE_KEY, type Cell, type WebCalendar } from "./types";

// /dat-san – bước 1: chọn khung giờ trên lưới (nhiều ô, nhiều sân, cùng 1 ngày, tối đa 16 ô); bước 2: nhập thông tin người đặt.
// Server tự tính giá và kiểm lại mọi điều kiện; FE chỉ gửi sân + giờ + thông tin khách (T-008 AC1–AC9).

const STORAGE_KEY = "wk-booking-v1";
// phone_token (30 phút) của SĐT đã xác minh OTP: dùng lại cho các lượt đặt kế tiếp, không bắt nhập mã lại
const PHONE_TOKEN_KEY = "wk-phone-token-v1";

type PhoneToken = { phone: string; token: string; expiresAt: string };
/** phone_token còn dùng được (còn > 15 giây) cho đúng SĐT này, không thì null. */
function savedToken(forPhone: string): string | null {
  const t = readJson<PhoneToken>(PHONE_TOKEN_KEY);
  return t && t.phone === forPhone && Date.parse(t.expiresAt) - Date.now() > 15_000 ? t.token : null;
}

// Kho nhỏ quanh sessionStorage để nhãn "đã xác minh" cập nhật khi lưu / xóa token (không setState trong effect)
const tokenListeners = new Set<() => void>();
const subscribeToken = (cb: () => void) => {
  tokenListeners.add(cb);
  return () => void tokenListeners.delete(cb);
};
const notifyToken = () => tokenListeners.forEach((l) => l());
const readTokenRaw = (): string | null => {
  try {
    return sessionStorage.getItem(PHONE_TOKEN_KEY);
  } catch {
    return null;
  }
};

type Me = { full_name: string; phone: string | null; phone_verified: boolean };

type Saved = { date: string; cells: Cell[]; name: string; phone: string; note: string; step: 1 | 2 };
type Restore = { date: string; items: Cell[] };

const cellKey = (c: Cell) => `${c.code}|${c.hour}`;
const pad2 = (n: number) => String(n).padStart(2, "0");
const range = (a: number, b: number) => `${pad2(a)}:00 – ${pad2(b)}:00`;

function readJson<T>(key: string): T | null {
  try {
    const raw = sessionStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}
function writeJson(key: string, value: unknown) {
  try {
    sessionStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* sessionStorage có thể bị chặn (chế độ riêng tư) – bỏ qua, không ảnh hưởng luồng đặt */
  }
}
function removeKey(key: string) {
  try {
    sessionStorage.removeItem(key);
  } catch {
    /* bỏ qua */
  }
}

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

type Props = { initialDate: string; today: string; hotline: string; texts: Dictionary["phoneVerify"] };

export function WebBookingFlow({ initialDate, today, hotline, texts }: Props) {
  const router = useRouter();
  const [date, setDate] = useState(initialDate);
  const [calendar, setCalendar] = useState<WebCalendar | null>(null);
  const [loadError, setLoadError] = useState("");
  const [cells, setCells] = useState<Cell[]>([]);
  const [step, setStep] = useState<1 | 2>(1);
  const [form, setForm] = useState({ name: "", phone: "", note: "" });
  const [touched, setTouched] = useState<{ name?: boolean; phone?: boolean; note?: boolean }>({});
  const [submitted, setSubmitted] = useState(false);
  const [banner, setBanner] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [pendingDate, setPendingDate] = useState<string | null>(null);
  // Bước nhập OTP (đang mở khi != null); khách đăng nhập đã xác minh SĐT thì bỏ qua (AC26)
  const [otp, setOtp] = useState<{ phone: string; resendAt: number | null; testOtp: string | null } | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [isGuest, setIsGuest] = useState(false); // /auth/me trả 401 ⇒ chưa đăng nhập (hiện gợi ý hội viên)
  // SĐT đã có phone_token (chỉ để đổi nhãn nút / hiện "đã xác minh"); hạn thật được kiểm lại lúc bấm nút
  const rawToken = useSyncExternalStore(subscribeToken, readTokenRaw, () => null);
  const verifiedPhone = useMemo(() => {
    try {
      return rawToken ? (JSON.parse(rawToken) as PhoneToken).phone : null;
    } catch {
      return null;
    }
  }, [rawToken]);
  const ids = { date: useId(), name: useId(), phone: useId(), note: useId() };

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
      const res = await getWebCalendar(d);
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
    [applyCells, applyStep],
  );

  // Lần đầu: khôi phục lựa chọn đã lưu trong tab (F5 không mất – AC9) rồi tải lịch.
  useEffect(() => {
    const saved = readJson<Saved>(STORAGE_KEY);
    if (saved && saved.date === initialDate) {
      /* eslint-disable react-hooks/set-state-in-effect -- khôi phục từ sessionStorage sau khi hydrate */
      applyCells(saved.cells ?? []);
      setForm({ name: saved.name ?? "", phone: saved.phone ?? "", note: saved.note ?? "" });
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
  }, [initialDate, applyCells, applyStep, load]);

  // Lưu lựa chọn + thông tin đã nhập vào sessionStorage của tab.
  useEffect(() => {
    if (!ready.current) return;
    writeJson(STORAGE_KEY, { date, cells, name: form.name, phone: form.phone, note: form.note, step } satisfies Saved);
  }, [date, cells, form, step]);

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
  const onlineOff = calendar ? !calendar.online_enabled : false;
  const holdMinutes = calendar?.hold_minutes ?? 5;

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

  // ---- Bước 2: kiểm tra + gửi ----
  const cleanName = form.name.trim().replace(/\s+/g, " ");
  const phone = normalizePhone(form.phone);
  const errors = {
    name: !cleanName ? "Vui lòng nhập họ tên." : cleanName.length > 100 ? "Họ tên tối đa 100 ký tự." : "",
    phone: !isValidPhone(phone) ? "Số điện thoại không hợp lệ — cần đủ 10 số." : "",
    note: form.note.trim().length > 200 ? "Ghi chú tối đa 200 ký tự." : "",
  };

  const skipOtp = Boolean(me?.phone_verified && me.phone && normalizePhone(me.phone) === phone);

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
        (key) => sendCheckout(key, { date, slots, full_name: cleanName, phone, ...(note ? { note } : {}), ...(phoneToken ? { phone_token: phoneToken } : {}) }),
        { retryRateLimit: false },
      );
      if (res.ok) {
        const token = res.data.token;
        if (!token) {
          setBanner("Không nhận được mã thanh toán. Vui lòng thử lại.");
          return;
        }
        removeKey(STORAGE_KEY);
        router.push(`/thanh-toan/${token}`);
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
      if (e.code === "E-WEB-8") {
        removeKey(PHONE_TOKEN_KEY);
        notifyToken();
      } // token hết hạn / không khớp SĐT ⇒ xác minh lại ở lần bấm kế tiếp
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
          <h2 className="text-2xl font-bold">Thông tin người đặt</h2>
          <p className="text-sm text-muted">Bước 2/3 · Nhập thông tin để nhận mã booking</p>
        </div>

        <section className="rounded-2xl border border-border bg-surface p-5" aria-labelledby="sum-title">
          <h3 id="sum-title" className="text-xs font-semibold tracking-wide text-muted uppercase">
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

        {isGuest ? <MemberHint next={`/dat-san?ngay=${date}`} /> : null}

        <section className="rounded-2xl border border-border bg-surface p-5">
          <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">Phiếu nhập thông tin</h3>
          <div className="mt-3 space-y-4">
            <div>
              <label htmlFor={ids.name} className="mb-1 block text-sm font-medium">
                Họ tên <span className="text-danger">*</span>
              </label>
              <input
                id={ids.name}
                value={form.name}
                maxLength={120}
                readOnly={otp !== null}
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
                readOnly={otp !== null}
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
              onVerified={(token, expiresAt, accountVerified) => {
                writeJson(PHONE_TOKEN_KEY, { phone: otp.phone, token, expiresAt } satisfies PhoneToken);
                notifyToken();
                // BE đã đánh dấu SĐT của tài khoản là đã xác minh ⇒ lần đặt sau bỏ OTP (AC40)
                if (accountVerified && me?.phone && normalizePhone(me.phone) === otp.phone) setMe({ ...me, phone_verified: true });
                setOtp(null);
                void submit(token); // đã xác minh: giữ chỗ + tạo thanh toán luôn
              }}
            />
          ) : (
            <button
              type="button"
              onClick={() => void submit()}
              disabled={busy || onlineOff}
              className="mt-5 w-full rounded-lg bg-primary px-4 py-3 text-sm font-semibold text-white disabled:opacity-60"
            >
              {busy ? "Đang xử lý…" : skipOtp || (isValidPhone(phone) && verifiedPhone === phone) ? "Xác nhận & thanh toán" : "Gửi mã xác minh"}
            </button>
          )}
          <p className="mt-2 text-center text-xs text-muted">Khung giờ được giữ {holdMinutes} phút để thanh toán, bắt đầu sau khi bạn xác minh số điện thoại.</p>
          {onlineOff ? (
            <p className="mt-2 text-center text-xs text-danger">Đặt online đang tạm ngưng. Vui lòng gọi hotline {hotline}.</p>
          ) : null}
        </section>
      </div>
    );
  }

  // ================= Bước 1 =================
  const hours = calendar?.columns ?? [];
  const openText =
    calendar && calendar.columns.length ? `Mở cửa ${pad2(calendar.columns[0])}:00 – ${pad2(calendar.columns[calendar.columns.length - 1] + 1)}:00 · ` : "";

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted">
        {openText}Đặt online thanh toán trước bằng chuyển khoản QR
      </p>

      <div>
        <label htmlFor={ids.date} className="mb-1 block text-sm font-medium">
          Chọn ngày
        </label>
        <div className="flex flex-wrap items-center gap-3">
          <input
            id={ids.date}
            type="date"
            value={date}
            min={today}
            onChange={(e) => onDateInput(e.target.value)}
            className="rounded-lg border border-border bg-surface px-3 py-2.5 text-sm"
          />
          <span className="text-sm text-muted" aria-live="polite">
            {formatLongDate(date)}
          </span>
        </div>
      </div>

      <section className="rounded-2xl border border-border bg-surface p-4" aria-label="Lịch sân">
        <ul className="mb-3 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted">
          <Legend swatch="border border-border bg-surface" text="Trắng = Trống" />
          <Legend swatch="bg-blk-paid" text="Đỏ = Đã đặt" />
          <Legend swatch="bg-blk-session" text="Tím = Sự kiện · đã đặt / tối đa người" />
          <Legend swatch="bg-cell-off" text="Xám = Không bán" />
          <Legend swatch="bg-primary" text="Xanh = Đang chọn" />
        </ul>

        {loadError ? (
          <div role="alert" className="space-y-2 py-6 text-center text-sm">
            <p className="text-danger">{loadError}</p>
            <button type="button" onClick={() => void load(date)} className="min-h-10 rounded-lg border border-border px-4 py-2">
              Thử lại
            </button>
          </div>
        ) : !calendar ? (
          <p className="py-10 text-center text-sm text-muted">Đang tải lịch sân…</p>
        ) : calendar.resources.length === 0 ? (
          <p className="py-10 text-center text-sm text-muted">Chưa có sân nào mở cho ngày này.</p>
        ) : (
          <div className={`relative overflow-x-auto ${loading ? "opacity-60" : ""}`} aria-busy={loading}>
            <div className="min-w-max [--c0:5.5rem] [--col:3.25rem] sm:[--c0:6.5rem] sm:[--col:3.5rem]">
              <div className="flex text-xs text-muted">
                <div className="sticky left-0 z-10 flex w-(--c0) shrink-0 items-center bg-surface pr-2">Sân</div>
                {hours.map((h) => (
                  <div key={h} className="w-(--col) shrink-0 pb-1 text-center">
                    {h}h
                  </div>
                ))}
              </div>
              {calendar.resources.map((r) => {
                const byHour = new Map(r.slots.map((s) => [s.start_hour, s]));
                return (
                  <div key={r.code} className="flex border-t border-border/60">
                    <div className="sticky left-0 z-10 flex w-(--c0) shrink-0 items-center bg-surface pr-2 text-sm font-medium">{r.name}</div>
                    {hours.map((h) => {
                      const s = byHour.get(h);
                      const base = "m-0.5 flex h-11 w-[calc(var(--col)-0.25rem)] shrink-0 flex-col items-center justify-center rounded-md text-[11px] leading-tight";
                      const label = `${r.name}, ${pad2(h)}:00 đến ${pad2(h + 1)}:00`;
                      if (!s || s.state === "closed") {
                        return <div key={h} role="img" aria-label={`${label}, không bán`} className={`${base} bg-cell-off`} />;
                      }
                      if (s.state === "booked") {
                        return (
                          <div key={h} role="img" aria-label={`${label}, đã đặt`} className={`${base} bg-blk-paid font-medium text-blk-paid-fg`}>
                            Đã đặt
                          </div>
                        );
                      }
                      if (s.state === "event") {
                        return (
                          <div key={h} role="img" aria-label={`${label}, sự kiện ${s.taken ?? 0} trên ${s.capacity ?? 0} người`} className={`${base} bg-blk-session text-blk-session-fg`}>
                            <span>Sự kiện</span>
                            <b className="text-xs">
                              {s.taken}/{s.capacity}
                            </b>
                          </div>
                        );
                      }
                      const on = selected.has(`${r.code}|${h}`);
                      return (
                        <button
                          key={h}
                          type="button"
                          onClick={() => toggle(r.code, h)}
                          disabled={loading}
                          aria-pressed={on}
                          aria-label={`${label}, trống${s.price != null ? `, ${formatVnd(s.price)}` : ""}`}
                          title={s.price != null ? formatVnd(s.price) : undefined}
                          className={`${base} border font-medium ${on ? "border-primary bg-primary text-white" : "border-border bg-surface hover:bg-primary-softer"} focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-primary`}
                        >
                          {on ? `${h}h–${h + 1}h` : null}
                        </button>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </section>

      {notice ? (
        <p role="status" className="rounded-lg border border-border bg-surface p-3 text-sm">
          {notice}
        </p>
      ) : null}

      <section className="sticky bottom-3 z-20 rounded-2xl border border-border bg-surface p-4 shadow-lg" aria-label="Bạn đang chọn">
        <div className="flex flex-wrap items-center gap-4">
          <div className="min-w-0 flex-1">
            <p className="text-xs text-muted">Bạn đang chọn</p>
            {groups.length ? (
              <ul className="max-h-28 overflow-y-auto text-sm font-semibold">
                {groups.map((g) => (
                  <li key={g.code}>
                    {g.name} · {formatLongDate(date)} · {g.ranges} ({g.hours.length} giờ)
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm font-semibold">Chưa chọn khung giờ</p>
            )}
            <p className="mt-0.5 text-xs text-muted">
              {groups.length
                ? `Khung giờ được giữ ${holdMinutes} phút sau khi bạn bấm Thanh toán.`
                : "Bấm vào ô trắng để chọn — có thể chọn nhiều khung giờ, nhiều sân trong cùng ngày"}
            </p>
            {onlineOff ? <p className="mt-1 text-xs text-danger">Đặt online đang tạm ngưng. Vui lòng gọi hotline {hotline}.</p> : null}
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right">
              <p className="text-xs text-muted">Tổng</p>
              <p className="text-lg font-bold tabular-nums">{formatVnd(total)}</p>
            </div>
            <button
              type="button"
              onClick={() => applyStep(2)}
              disabled={!cells.length || onlineOff || !calendar}
              className="rounded-lg bg-primary px-6 py-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
            >
              Tiếp tục
            </button>
          </div>
        </div>
      </section>

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
      <span aria-hidden className={`inline-block size-3.5 rounded-sm ${swatch}`} />
      {text}
    </li>
  );
}
