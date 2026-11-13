"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { CourtGrid } from "@/components/court-grid/court-grid";
import { MyBookingModal } from "@/components/member-area/cell-dialogs";
import { MEMBER_BACK_EVENT } from "@/components/member-area/member-shell";
import { getMemberCalendar } from "@/components/member-area/cell-requests";
import { Modal } from "@/components/ui/modal";
import type { Dictionary } from "@/i18n/dictionaries";
import { otpErrorText, otpResendAt } from "@/lib/api/auth";
import { api } from "@/lib/api/client";
import { errorText, write } from "@/lib/api/write";
import { cn } from "@/lib/cn";
import { formatLongDate } from "@/lib/format";
import { TIERS } from "@/app/admin/hoi-vien/_components/member-params";
import type { SiteBranding } from "@/lib/api/server";
import { isValidPhone, normalizePhone } from "@/lib/phone";
import { BookingBar } from "./booking-bar";
import { BookingConfirm, type OtpStep } from "./booking-confirm";
import { LegendItems, tierOrderWrong } from "./booking-parts";
import { cellKey, pad2, summarize } from "./booking-summary";
import { DayStrip } from "./day-strip";
import { useGridRows, type GridClock } from "./use-grid-rows";
import { Step1Layout } from "./step1-layouts";
import { EventDialog } from "./event-dialog";
import { checkoutSeedKey, clearToken, readJson, removeKey, saveToken, savedToken, useVerifiedPhone, writeJson } from "./session-store";
import { toast } from "@/lib/feedback";
import type { VerifiedAccount } from "./phone-otp";
import { HOLD_CANCELLED_EVENT, usePendingGate } from "./pending-dialogs";
import { getWebCalendar, requestBookingPhone, sendCheckout } from "./requests";
import { ownsCell, readPending } from "./pending-checkout";
import { MAX_CELLS, RESTORE_KEY, type Cell, type SlotExtra, type WebCalendar } from "./types";

// /dat-san – bước 1: chọn khung giờ trên lưới (nhiều ô, nhiều sân, cùng 1 ngày, tối đa 16 ô); bước 2: nhập thông tin người đặt.
// Server tự tính giá và kiểm lại mọi điều kiện; FE chỉ gửi sân + giờ + thông tin khách (T-008 AC1–AC9).

const STORAGE_KEY = "wk-booking-v1";
type Me = { full_name: string; phone: string | null; phone_verified: boolean };

// Thông tin đã nhập trong tab (ô đã chọn / bước không lưu: mở màn luôn là lưới trống – người dùng 13/11)
type Saved = { date: string; name: string; phone: string; note: string; minTier?: string; maxTier?: string };
type Restore = { date: string; items: Cell[] };

/** Đặt trong khu hội viên (T-018 AC4): họ tên + SĐT lấy từ hồ sơ, khóa; bỏ OTP; server nhận `as_member`. */
export type MemberIdentity = { name: string; phone: string };

/** Thông tin sân cần cho luồng đặt (trang server truyền xuống từ getBranding). */
export type BookingVenue = Pick<SiteBranding, "name" | "address" | "phone">;

type Props = {
  initialDate: string;
  today: string;
  venue: BookingVenue;
  texts: Dictionary["phoneVerify"];
  member?: MemberIdentity;
  /** `?event=` (T-023 AC18): tự mở popup sự kiện này khi vào trang */
  initialEvent?: string | null;
};

export function WebBookingFlow({ initialDate, today, venue, texts, member, initialEvent = null }: Props) {
  const router = useRouter();
  // Phiên đặt trong khu hội viên lưu riêng, không lẫn với /dat-san công khai
  const storageKey = member ? `${STORAGE_KEY}:member` : STORAGE_KEY;
  const [date, setDate] = useState(initialDate);
  const [calendar, setCalendar] = useState<WebCalendar | null>(null);
  const [loadError, setLoadError] = useState("");
  const [cells, setCells] = useState<Cell[]>([]);
  const [step, setStep] = useState<1 | 2>(1);
  const [form, setForm] = useState({ name: member?.name ?? "", phone: member?.phone ?? "", note: "" });
  // Khoảng hạng của phòng (T-031): chỉ hội viên chọn, chỉ lúc đặt; "" = không giới hạn
  const [tiers, setTiers] = useState({ min: "", max: "" });
  const [touched, setTouched] = useState<{ name?: boolean; phone?: boolean; note?: boolean }>({});
  const [submitted, setSubmitted] = useState(false);
  const [banner, setBanner] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  // Còn đơn chờ thanh toán ⇒ không cho sang bước 2 / tạo đơn mới (hộp: Thanh toán ngay / Hủy giữ chỗ)
  const gate = usePendingGate(Boolean(member));
  const [loading, setLoading] = useState(false);
  const [pendingDate, setPendingDate] = useState<string | null>(null);
  // Đồng hồ cho ô đang giữ chỗ (T-075): giờ máy lúc vẽ + lệch so với giờ server của lần tải lịch gần nhất
  const [clock, setClock] = useState<GridClock>({ nowMs: 0, offset: 0 });
  // Hội viên bấm ô "Sân của bạn" / "Sự kiện" (T-023): hộp thoại tương ứng; `opener` để trả focus về ô khi đóng
  const [cellDialog, setCellDialog] = useState<{ kind: "mine" | "event"; code: string } | null>(initialEvent ? { kind: "event", code: initialEvent } : null);
  const openerRef = useRef<HTMLElement | null>(null);
  // Bước nhập OTP (đang mở khi != null); khách đăng nhập đã xác minh SĐT thì bỏ qua (AC26)
  const [otp, setOtp] = useState<OtpStep | null>(null);
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

  // Khu hội viên: đang ở bước 2 mà bấm nút quay lại trên app bar ⇒ lùi về chọn giờ, không rời màn Đặt sân
  useEffect(() => {
    if (!member) return;
    const onBack = (e: Event) => {
      if (stepRef.current !== 2) return;
      e.preventDefault();
      applyStep(1);
    };
    window.addEventListener(MEMBER_BACK_EVENT, onBack);
    return () => window.removeEventListener(MEMBER_BACK_EVENT, onBack);
  }, [member, applyStep]);

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
      const now = Date.now();
      setClock({ nowMs: now, offset: Date.parse(cal.server_now) - now });
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
      // Ô đã chọn giờ là ô chính mình đang giữ (lượt chờ thanh toán) ⇒ bỏ lặng lẽ, không báo "có người đặt"
      const mineHeld = new Set<string>();
      const own = readPending(Boolean(member));
      for (const r of cal.resources) {
        for (const s of r.slots as ((typeof r.slots)[number] & SlotExtra)[]) {
          if (s.state === "held" && (s.holding || ownsCell(own, cal.date, r.code, s.start_hour))) mineHeld.add(`${r.code}|${s.start_hour}`);
        }
      }
      const lost = cur.filter((c) => !freeSet.has(cellKey(c)) && !mineHeld.has(cellKey(c)));
      if (!lost.length && cur.some((c) => mineHeld.has(cellKey(c)))) applyCells(cur.filter((c) => freeSet.has(cellKey(c))));
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

  // Trang được dựng lại / hiện lại từ bộ nhớ (effect chạy lại) ⇒ lưới chọn giờ mặc định: bước 1, chưa chọn ô nào (người dùng 13/11)
  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect -- về lưới trống mỗi lần màn được hiện */
    applyStep(1);
    applyCells([]);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [applyStep, applyCells]);

  // Lần đầu (và mỗi lần trang được hiện lại): khôi phục thông tin đã nhập trong tab (tên, SĐT, ghi chú, khoảng hạng) rồi tải lịch.
  useEffect(() => {
    const saved = readJson<Saved>(storageKey);
    if (saved && saved.date === initialDate) {
      // Không khôi phục ô đã chọn / bước 2: mở màn là lưới trống (người dùng 13/11); chỉ giữ thông tin đã nhập
      /* eslint-disable react-hooks/set-state-in-effect -- khôi phục từ sessionStorage sau khi hydrate */
      setForm({ name: member?.name ?? saved.name ?? "", phone: member?.phone ?? saved.phone ?? "", note: saved.note ?? "" });
      if (member) setTiers({ min: TIERS.some((t) => t === saved.minTier) ? (saved.minTier ?? "") : "", max: TIERS.some((t) => t === saved.maxTier) ? (saved.maxTier ?? "") : "" });
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

  // Lưu thông tin đã nhập vào sessionStorage của tab.
  useEffect(() => {
    if (!ready.current) return;
    writeJson(storageKey, { date, name: form.name, phone: form.phone, note: form.note, minTier: tiers.min, maxTier: tiers.max } satisfies Saved);
  }, [date, form, storageKey, tiers]);

  // Vừa hủy giữ chỗ (hộp chặn đơn mới / màn QR) ⇒ tải lại ngay: ô "Chờ bạn thanh toán" trống lại
  useEffect(() => {
    // Hủy trong hộp chặn đơn mới (kể cả lúc đang ở màn xác nhận) ⇒ về lưới chọn giờ, giữ các ô đang chọn, tải lại lịch
    const onCancelled = () => {
      applyStep(1);
      void load(dateRef.current, true);
    };
    window.addEventListener(HOLD_CANCELLED_EVENT, onCancelled);
    return () => window.removeEventListener(HOLD_CANCELLED_EVENT, onCancelled);
  }, [load, applyStep]);

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
  // Mở hộp "Sân của bạn" / "Sự kiện"; `opener` để trả focus về ô khi đóng
  const openCell = useCallback((kind: "mine" | "event", code: string, el: HTMLElement) => {
    openerRef.current = el;
    setCellDialog({ kind, code });
  }, []);
  const reloadQuiet = useCallback(() => void load(dateRef.current, true), [load]);
  const gridRows = useGridRows({ calendar, date, member: Boolean(member), clock, setClock, reload: reloadQuiet, onOpen: openCell });
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

  const tierOrderError = Boolean(member) && tierOrderWrong(tiers.min, tiers.max);

  const skipOtp = Boolean(member) || Boolean(me?.phone_verified && me.phone && normalizePhone(me.phone) === phone);

  /** Bấm nút chính: kiểm form → (cần thì) gửi mã OTP → khi có phone_token mới tạo checkout. */
  async function submit(tokenOverride?: string) {
    setSubmitted(true);
    setBanner("");
    if (tierOrderError || errors.name || errors.phone || errors.note || !calendar || !cells.length) {
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
        (key) => sendCheckout(key, { date, slots, full_name: cleanName, phone, as_member: Boolean(member), ...(member && tiers.min ? { min_tier: tiers.min as (typeof TIERS)[number] } : {}), ...(member && tiers.max ? { max_tier: tiers.max as (typeof TIERS)[number] } : {}), ...(note ? { note } : {}), ...(phoneToken ? { phone_token: phoneToken } : {}) }),
        { retryRateLimit: false },
      );
      if (res.ok) {
        const token = res.data.token;
        if (!token) {
          setBanner("Không nhận được mã thanh toán. Vui lòng thử lại.");
          return;
        }
        removeKey(storageKey);
        // Không lưu lượt chờ ở đây: lưu là thẻ "Đang giữ chỗ" hiện ngay trên màn này trước khi sang QR (nháy) – màn QR tự lưu lần tải đầu
        // Sang ngay màn thanh toán (người dùng 13/11), đưa sẵn đơn để màn đó hiện QR không phải tải lại; KHÔNG đổi gì trên màn này
        // (đổi ngay sẽ nháy về lưới chọn giờ) – lúc quay lại màn này luôn mở ở lưới trống
        writeJson(checkoutSeedKey(token), res.data);
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
      if (gate.fromError(e)) return;
      if (e.code === "E-WEB-5") void load(dateRef.current, true);
      if (e.code === "E-WEB-8") clearToken(); // token hết hạn / không khớp SĐT ⇒ xác minh lại ở lần bấm kế tiếp
      setBanner(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const showErr = (k: "name" | "phone" | "note") => Boolean(submitted || touched[k]) && errors[k];

  // ================= Bước 2 =================
  if (step === 2 && calendar) {
    return (
      <BookingConfirm
        venue={venue}
        date={date}
        groups={groups}
        totalHours={totalHours}
        total={total}
        holdMinutes={holdMinutes}
        member={Boolean(member)}
        isGuest={isGuest}
        tiers={tiers}
        setTiers={setTiers}
        form={form}
        setForm={setForm}
        onTouch={(k) => setTouched((t) => ({ ...t, [k]: true }))}
        errorOf={showErr}
        ids={ids}
        otp={otp}
        texts={texts}
        phoneVerified={isValidPhone(phone) && (skipOtp || verifiedPhone === phone)}
        readyToPay={skipOtp || (isValidPhone(phone) && verifiedPhone === phone)}
        busy={busy}
        onlineOff={onlineOff}
        banner={banner}
        onBack={() => applyStep(1)}
        onSubmit={() => void submit()}
        onChangePhone={() => setOtp(null)}
        onVerified={(token, expiresAt, accountVerified, account) => {
          if (!otp) return;
          saveToken({ phone: otp.phone, token, expiresAt });
          // BE đã đánh dấu SĐT của tài khoản là đã xác minh ⇒ lần đặt sau bỏ OTP (AC40)
          if (accountVerified && me?.phone && normalizePhone(me.phone) === otp.phone) setMe({ ...me, phone_verified: true });
          afterAccountVerified(account);
          setOtp(null);
          void submit(token); // đã xác minh: giữ chỗ + tạo thanh toán luôn
        }}
        dialog={gate.dialog}
      />
    );
  }

  // ================= Bước 1 =================
  const hours = calendar?.columns ?? [];

  return (
    <div className={cn("space-y-4", cells.length > 0 && "pb-24 sm:pb-0")}>
      <Step1Layout
        dayStrip={<DayStrip date={date} today={today} onPick={onDateInput} flat />}
        dateLabel={formatLongDate(date)}
        legendItems={<LegendItems member={Boolean(member)} />}
        alert={onlineOff ? `Đặt online đang tạm ngưng. Vui lòng gọi hotline ${venue.phone}.` : null}
        grid={
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
          </section>
        }
        notice={
          notice ? (
              <p role="status" className="rounded-lg border border-border bg-surface p-3 text-sm">
                {notice}
              </p>
          ) : null
        }
        bar={
          cells.length > 0 ? (
            <BookingBar groups={groups} totalHours={totalHours} total={total} holdMinutes={holdMinutes} disabled={onlineOff || !calendar} onNext={() => !gate.check() && applyStep(2)} />
          ) : null
        }
      />

      {member ? <MyBookingModal orderCode={cellDialog?.kind === "mine" ? cellDialog.code : null} onClose={closeCellDialog} /> : null}
      <EventDialog
        eventCode={cellDialog?.kind === "event" ? cellDialog.code : null}
        date={date}
        member={member}
        venue={venue}
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
      {gate.dialog}
    </div>
  );
}
