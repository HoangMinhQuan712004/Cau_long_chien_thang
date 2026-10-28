"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { btnCls, btnPrimaryCls, ErrorBanner, Hint, inputCls } from "@/components/booking-engine/ui";
import { Modal } from "@/components/ui/modal";
import { CopyButton } from "@/components/web-booking/pay-parts";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatDayMonthYear, formatTime, formatVnd, vnDate } from "@/lib/format";
import { getPaymentSettings, sendSavePaymentSettings, sendSimulate } from "./payment-settings-requests";
import { MISSING_LABEL, type BankOption, type PaymentSettings } from "./payment-settings-types";

// /admin/cai-dat/thanh-toan (chỉ Admin): tài khoản nhận tiền, khóa SePay, bật/tắt đặt online (T-012 AC1–AC7).
// Rủi ro chính: kẻ chiếm phiên Admin đổi số tài khoản nhận tiền → mọi lần lưu đều nhập lại mật khẩu; khóa chỉ nhập, không bao giờ hiện lại.

const hhmmDate = (iso: string) => `${formatTime(iso)} ${formatDayMonthYear(vnDate(iso))}`;

/** Tên chủ tài khoản: viết hoa, bỏ dấu, chỉ A–Z và khoảng trắng. */
export function normalizeAccountName(v: string): string {
  return v
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/đ/gi, "d")
    .toUpperCase()
    .replace(/[^A-Z ]/g, "")
    .replace(/ {2,}/g, " ")
    .replace(/^ /, "");
}

type Form = { bank: string; account: string; name: string; toggle: boolean; secret: string; changingSecret: boolean };

const toForm = (s: PaymentSettings): Form => ({
  bank: s.bank_code ?? "",
  account: s.account_number ?? "",
  name: s.account_name ?? "",
  toggle: s.online_toggle,
  secret: "",
  changingSecret: !s.secret_set,
});

export function PaymentSettingsScreen({ initial, banks }: { initial: PaymentSettings; banks: BankOption[] }) {
  const [settings, setSettings] = useState(initial);
  const [form, setForm] = useState<Form>(() => toForm(initial));
  const [bankQuery, setBankQuery] = useState("");
  const [showSecret, setShowSecret] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [banner, setBanner] = useState("");
  const ids = { bankSearch: useId(), bank: useId(), account: useId(), name: useId(), secret: useId() };

  // ---- Kiểm tra ----
  const accountOk = /^\d{6,20}$/.test(form.account);
  const nameTrim = form.name.trim();
  const nameOk = nameTrim.length >= 2 && nameTrim.length <= 50;
  const secretTyped = form.secret.length > 0;
  const secretOk = !secretTyped || (form.secret.length >= 16 && form.secret.length <= 128);
  const hasSecret = (settings.secret_set && !form.changingSecret) || (secretTyped && secretOk);
  const missing: string[] = [];
  if (!form.bank) missing.push(MISSING_LABEL.bank);
  if (!accountOk) missing.push(MISSING_LABEL.account_number);
  if (!nameOk) missing.push(MISSING_LABEL.account_name);
  if (!hasSecret) missing.push(MISSING_LABEL.webhook_secret);
  const canEnable = missing.length === 0;
  const effectiveToggle = form.toggle && canEnable;

  const base = toForm(settings);
  const dirty =
    form.bank !== base.bank ||
    form.account !== base.account ||
    form.name !== base.name ||
    effectiveToggle !== settings.online_toggle ||
    (form.changingSecret && secretTyped);
  const valid = Boolean(form.bank) && accountOk && nameOk && secretOk;
  const accountChanged = form.bank !== base.bank || form.account !== base.account;
  const pendingBlock = accountChanged && settings.pending_checkouts > 0;

  const filteredBanks = useMemo(() => {
    const q = bankQuery.trim().toLowerCase();
    return banks.filter((b) => b.code === form.bank || !q || `${b.short_name} ${b.name} ${b.code}`.toLowerCase().includes(q));
  }, [banks, bankQuery, form.bank]);
  const bankLabel = (code: string) => banks.find((b) => b.code === code)?.short_name ?? code;

  const qrSrc =
    form.bank && accountOk
      ? `https://qr.sepay.vn/img?acc=${encodeURIComponent(form.account)}&bank=${encodeURIComponent(bankLabel(form.bank))}&amount=10000&des=BK00000000000`
      : null;

  const set = (p: Partial<Form>) => setForm((f) => ({ ...f, ...p }));

  async function reload() {
    const res = await getPaymentSettings();
    if (res.ok) {
      setSettings(res.data);
      setForm(toForm(res.data));
      setBanner("");
    } else {
      toast(errorText(res.error), undefined, "error");
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Cài đặt thanh toán online</h1>
        <p className="mt-1 text-sm text-muted">Tài khoản nhận tiền khi khách đặt sân trên web, và kết nối với SePay để hệ thống tự xác nhận khi tiền về.</p>
      </div>

      <StatusBlock s={settings} />

      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}

      <Card title="Tài khoản nhận tiền">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label htmlFor={ids.bankSearch} className="mb-1 block text-sm font-medium">
              Ngân hàng <span className="text-danger">*</span>
            </label>
            <input id={ids.bankSearch} type="search" value={bankQuery} placeholder="Gõ để tìm ngân hàng…" onChange={(e) => setBankQuery(e.target.value)} className={`${inputCls} mb-2`} />
            <select
              id={ids.bank}
              aria-label="Chọn ngân hàng"
              value={form.bank}
              onChange={(e) => set({ bank: e.target.value })}
              className={inputCls}
              size={bankQuery.trim() ? Math.min(6, Math.max(2, filteredBanks.length + 1)) : undefined}
            >
              <option value="">— Chọn ngân hàng —</option>
              {filteredBanks.map((b) => (
                <option key={b.code} value={b.code}>
                  {b.short_name} – {b.name}
                </option>
              ))}
            </select>
            {bankQuery.trim() && filteredBanks.length === 0 ? <p className="mt-1 text-xs text-muted">Không có ngân hàng phù hợp.</p> : null}
          </div>
          <div>
            <label htmlFor={ids.account} className="mb-1 block text-sm font-medium">
              Số tài khoản <span className="text-danger">*</span>
            </label>
            <input
              id={ids.account}
              value={form.account}
              inputMode="numeric"
              autoComplete="off"
              maxLength={20}
              onChange={(e) => set({ account: e.target.value.replace(/\D/g, "") })}
              aria-invalid={Boolean(form.account && !accountOk) || undefined}
              className={inputCls}
            />
            <p className={`mt-1 text-xs ${form.account && !accountOk ? "text-danger" : "text-muted"}`}>Số tài khoản gồm 6–20 chữ số.</p>
          </div>
          <div>
            <label htmlFor={ids.name} className="mb-1 block text-sm font-medium">
              Chủ tài khoản <span className="text-danger">*</span>
            </label>
            <input
              id={ids.name}
              value={form.name}
              autoComplete="off"
              maxLength={50}
              onChange={(e) => set({ name: normalizeAccountName(e.target.value) })}
              aria-invalid={Boolean(form.name && !nameOk) || undefined}
              className={inputCls}
            />
            <p className={`mt-1 text-xs ${form.name && !nameOk ? "text-danger" : "text-muted"}`}>Tự viết hoa, bỏ dấu (2–50 ký tự A–Z).</p>
          </div>
        </div>

        {pendingBlock ? (
          <ErrorBanner>
            Đang có {settings.pending_checkouts} lượt chờ thanh toán. Tắt Nhận đặt online, đợi các lượt hết hạn (tối đa 6 phút) rồi đổi tài khoản.{" "}
            <button type="button" onClick={reload} className="font-medium underline">
              Tải lại
            </button>
          </ErrorBanner>
        ) : null}

        <div className="mt-5 rounded-lg border border-border bg-background p-4">
          <p className="text-sm font-medium">Xem trước mã QR mẫu</p>
          {qrSrc ? (
            <div className="mt-3 flex flex-col gap-4 sm:flex-row sm:items-center">
              <div className="mx-auto shrink-0 rounded-xl border border-border bg-white p-2 sm:mx-0">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={qrSrc} alt="Mã QR mẫu 10.000 đồng, nội dung BK00000000000" width={160} height={160} referrerPolicy="no-referrer" className="size-40" />
              </div>
              <div className="text-sm text-muted">
                <p>
                  {bankLabel(form.bank)} · {form.account} · 10.000đ · nội dung <b className="text-foreground">BK00000000000</b>
                </p>
                <p className="mt-2">Quét thử bằng app ngân hàng: hiện đúng tên chủ tài khoản là được. <b>Không cần chuyển tiền.</b></p>
              </div>
            </div>
          ) : (
            <p className="mt-2 text-sm text-muted">Chọn ngân hàng và nhập số tài khoản hợp lệ để xem mã QR mẫu.</p>
          )}
        </div>
      </Card>

      <Card title="Kết nối SePay">
        <div className="space-y-4">
          <div>
            <span className="mb-1 block text-sm font-medium">URL webhook</span>
            <div className="flex flex-wrap items-center gap-2">
              <code className="min-w-0 flex-1 break-all rounded-md border border-border bg-background px-3 py-2 text-sm">{settings.webhook_url}</code>
              <CopyButton text={settings.webhook_url} label="URL webhook" />
            </div>
            <p className="mt-1 text-xs text-muted">Mẫu mã thanh toán: {settings.pay_code_hint || "Tiền tố BK + 11 chữ số"}.</p>
          </div>

          <div>
            <label htmlFor={ids.secret} className="mb-1 block text-sm font-medium">
              Khóa bí mật webhook (HMAC)
            </label>
            {settings.secret_set && !form.changingSecret ? (
              <div className="flex flex-wrap items-center gap-3">
                <span className="rounded-md border border-border bg-background px-3 py-2 font-mono text-sm" aria-label={`Đã đặt khóa, 4 ký tự cuối ${settings.secret_last4 ?? ""}`}>
                  ••••{settings.secret_last4 ?? ""}
                </span>
                <button type="button" onClick={() => set({ changingSecret: true })} className={btnCls}>
                  Đổi khóa
                </button>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <input
                  id={ids.secret}
                  type={showSecret ? "text" : "password"}
                  value={form.secret}
                  autoComplete="new-password"
                  spellCheck={false}
                  maxLength={128}
                  placeholder="Dán khóa từ SePay (16–128 ký tự)"
                  onChange={(e) => set({ secret: e.target.value.trim() })}
                  aria-invalid={Boolean(secretTyped && !secretOk) || undefined}
                  className={`${inputCls} min-w-0 flex-1`}
                />
                <button type="button" onClick={() => setShowSecret((v) => !v)} className={btnCls} aria-pressed={showSecret}>
                  {showSecret ? "Ẩn" : "Hiện"}
                </button>
                {settings.secret_set ? (
                  <button type="button" onClick={() => { set({ changingSecret: false, secret: "" }); setShowSecret(false); }} className={btnCls}>
                    Giữ khóa cũ
                  </button>
                ) : null}
              </div>
            )}
            <p className={`mt-1 text-xs ${secretTyped && !secretOk ? "text-danger" : "text-muted"}`}>
              {secretTyped && !secretOk ? "Khóa bí mật 16–128 ký tự." : "Chỉ nhập, không bao giờ hiện lại sau khi lưu."}
            </p>
          </div>

          <details className="rounded-lg border border-border bg-background p-4 text-sm">
            <summary className="cursor-pointer font-medium">Hướng dẫn SePay (5 bước)</summary>
            <ol className="mt-3 list-decimal space-y-2 pl-5 text-muted">
              <li>Đăng ký tại <a className="text-primary underline" href="https://my.sepay.vn" target="_blank" rel="noopener noreferrer">my.sepay.vn</a>, chọn gói, <b>liên kết tài khoản ngân hàng</b> nhận tiền của sân.</li>
              <li><b>Cấu trúc mã thanh toán</b> (Công ty → Cấu hình chung): tiền tố <code>BK</code>, hậu tố 11 ký tự <b>số</b>.</li>
              <li><b>Webhooks → + Thêm webhook</b>: sự kiện <b>Có tiền vào</b>; URL = URL ở trên; tài khoản = tài khoản vừa liên kết; lọc tiền tố <code>BK</code>; bảo mật <b>HMAC-SHA256</b> → tạo khóa, <b>chép ngay</b> (SePay chỉ hiện một lần) → dán vào ô Khóa bí mật ở trên.</li>
              <li>Ở trang này: chọn ngân hàng, nhập số tài khoản, chủ tài khoản, <b>dán khóa</b> vào ô Khóa bí mật rồi bấm <b>Lưu</b> (để công tắc Nhận đặt online tắt cũng được).</li>
              <li>Trên SePay bấm <b>Gửi thử</b> → mục “Lần cuối nhận thông báo từ SePay” ở đầu trang phải hiện vừa xong. Sau đó mới bật <b>Nhận đặt online</b> và Lưu. Thử một lượt đặt thật với tiền sân nhỏ nhất.</li>
            </ol>
            <p className="mt-3 text-xs text-muted">
              Thử không tốn tiền: bật Test Mode trên SePay → Giao dịch → “+ Mô phỏng giao dịch” (webhook Test Mode cấu hình riêng, trỏ vào link dev). Tài liệu:{" "}
              <a className="text-primary underline" href="https://docs.sepay.vn" target="_blank" rel="noopener noreferrer">docs.sepay.vn</a>.
            </p>
          </details>
        </div>
      </Card>

      <Card title="Nhận đặt online">
        <div className="flex items-start gap-4">
          <button
            type="button"
            role="switch"
            aria-checked={effectiveToggle}
            aria-labelledby="toggle-label"
            disabled={!canEnable}
            onClick={() => set({ toggle: !effectiveToggle })}
            className={`relative mt-0.5 h-7 w-12 shrink-0 rounded-full border border-border transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${effectiveToggle ? "bg-primary" : "bg-busy"}`}
          >
            <span aria-hidden className={`absolute top-0.5 size-5 rounded-full bg-white shadow transition-all ${effectiveToggle ? "left-6" : "left-0.5"}`} />
          </button>
          <div className="min-w-0">
            <p id="toggle-label" className="text-sm font-medium">
              {effectiveToggle ? "Đang nhận đặt online" : "Đang tắt"}
            </p>
            {canEnable ? (
              <p className="mt-0.5 text-xs text-muted">Khi tắt, khách vẫn xem lịch nhưng không đặt được; nút Tiếp tục sẽ khóa kèm số hotline.</p>
            ) : (
              <p className="mt-0.5 text-xs text-muted">Chưa bật được vì còn thiếu: {missing.join(", ")}.</p>
            )}
          </div>
        </div>
      </Card>

      <div className="sticky bottom-3 z-20 flex flex-wrap items-center gap-3 rounded-2xl border border-border bg-surface p-3 shadow-lg">
        <p className="text-xs text-muted">{dirty ? "Có thay đổi chưa lưu. Mỗi lần lưu cần nhập lại mật khẩu Admin." : "Chưa có thay đổi."}</p>
        <div className="ml-auto flex gap-2">
          <button type="button" onClick={() => { setForm(toForm(settings)); setBanner(""); setShowSecret(false); }} disabled={!dirty} className={btnCls}>
            Hủy thay đổi
          </button>
          <button type="button" onClick={() => { setBanner(""); setConfirming(true); }} disabled={!dirty || !valid} className={btnPrimaryCls}>
            Lưu
          </button>
        </div>
      </div>

      {settings.simulate_enabled ? <SimulateBlock onDone={reload} /> : null}

      {confirming ? (
        <ConfirmDialog
          onClose={() => setConfirming(false)}
          onSubmit={async (password) => {
            const res = await write(
              (key) =>
                sendSavePaymentSettings(key, {
                  bank_code: form.bank,
                  account_number: form.account,
                  account_name: nameTrim,
                  online_toggle: effectiveToggle,
                  webhook_secret: form.changingSecret && secretTyped ? form.secret : null,
                  current_password: password,
                }),
              { retryRateLimit: false }, // E-SEC-5 = khóa 15 phút: báo ngay, không tự gửi lại mật khẩu
            );
            if (res.ok) {
              const next = res.data;
              setSettings(next);
              setForm(toForm(next));
              setShowSecret(false);
              setConfirming(false);
              toast("Đã lưu cài đặt thanh toán.");
              return null;
            }
            const e = res.error;
            if (e.code === "E-AUTH-7") return "Mật khẩu không đúng.";
            if (e.status === 429 || e.code === "E-SEC-5") return "Bạn đã nhập sai quá nhiều lần. Vui lòng thử lại sau 15 phút.";
            if (e.code === "E-PAY-3") {
              setConfirming(false);
              await reload(); // lấy lại số lượt chờ mới nhất
              setBanner(errorText(e));
              return null;
            }
            return errorText(e);
          }}
        />
      ) : null}
    </div>
  );
}

function StatusBlock({ s }: { s: PaymentSettings }) {
  let badge: { text: string; cls: string };
  if (s.online_enabled) badge = { text: "Đang nhận đặt online", cls: "bg-free text-success" };
  else if (s.online_toggle && s.missing.length) badge = { text: `Thiếu cấu hình: ${s.missing.map((m) => MISSING_LABEL[m]).join(", ")}`, cls: "bg-blk-unpaid text-blk-unpaid-fg" };
  else badge = { text: "Đang tắt", cls: "bg-blk-bad text-blk-bad-fg" };
  return (
    <section className="rounded-2xl border border-border bg-surface p-5" aria-label="Trạng thái">
      <h2 className="text-xs font-semibold tracking-wide text-muted uppercase">Trạng thái</h2>
      <p className="mt-2">
        <span className={`inline-block rounded-full px-3 py-1 text-sm font-semibold ${badge.cls}`}>{badge.text}</span>
      </p>
      <dl className="mt-3 space-y-1 text-sm">
        <div className="flex flex-wrap gap-x-2">
          <dt className="text-muted">Lần cuối nhận thông báo từ SePay:</dt>
          <dd className="font-medium">{s.last_webhook_at ? hhmmDate(s.last_webhook_at) : "Chưa nhận lần nào"}</dd>
        </div>
        <div className="flex flex-wrap gap-x-2">
          <dt className="text-muted">Đổi lần cuối:</dt>
          <dd className="font-medium">{s.updated_at ? `${hhmmDate(s.updated_at)}${s.updated_by_label ? ` bởi ${s.updated_by_label}` : ""}` : "Chưa đổi lần nào"}</dd>
        </div>
      </dl>
    </section>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-border bg-surface p-5" aria-label={title}>
      <h2 className="mb-4 text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

/** Nhập lại mật khẩu Admin để lưu. `onSubmit` trả thông báo lỗi (hiện ngay trong hộp) hoặc null khi xong. */
function ConfirmDialog({ onClose, onSubmit }: { onClose: () => void; onSubmit: (password: string) => Promise<string | null> }) {
  const pwId = useId();
  const pwRef = useRef<HTMLInputElement>(null);
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // <dialog>.showModal() chạy sau khi ô được mount nên `autoFocus` của React bị bỏ qua; effect của cha chạy sau effect của Modal.
  useEffect(() => {
    pwRef.current?.focus();
  }, []);

  async function submit() {
    if (!password) {
      setError("Vui lòng nhập mật khẩu.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const msg = await onSubmit(password);
      if (msg) setError(msg);
    } finally {
      setPassword(""); // không giữ mật khẩu trong bộ nhớ sau khi gửi
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title="Xác nhận bằng mật khẩu"
      footer={
        <>
          <button type="button" onClick={onClose} disabled={busy} className={btnCls}>
            Hủy
          </button>
          <button type="button" onClick={submit} disabled={busy} className={btnPrimaryCls}>
            {busy ? "Đang lưu…" : "Xác nhận và lưu"}
          </button>
        </>
      }
    >
      <Hint>Thay đổi tài khoản nhận tiền ảnh hưởng trực tiếp đến tiền của sân. Nhập lại mật khẩu Admin để xác nhận.</Hint>
      {error ? <ErrorBanner>{error}</ErrorBanner> : null}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <label htmlFor={pwId} className="mb-1 block text-sm font-medium">
          Mật khẩu Admin
        </label>
        <div className="flex gap-2">
          <input
            id={pwId}
            ref={pwRef}
            type={show ? "text" : "password"}
            value={password}
            autoComplete="current-password"
            maxLength={128}
            onChange={(e) => setPassword(e.target.value)}
            className={`${inputCls} min-w-0 flex-1`}
          />
          <button type="button" onClick={() => setShow((v) => !v)} className={btnCls} aria-pressed={show}>
            {show ? "Ẩn" : "Hiện"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

const OUTCOME_TEXT = {
  applied: "Đã nhận tiền",
  partial: "Trả thiếu",
  refund_needed: "Cần hoàn tiền",
  unmatched: "Không khớp mã",
  ignored: "Bỏ qua",
} as const;

/** Chỉ hiện ở môi trường thử (`simulate_enabled`): gọi `POST /payments/dev/simulate` đi đúng đường xử lý của webhook. */
function SimulateBlock({ onDone }: { onDone: () => void | Promise<void> }) {
  const ids = { ref: useId(), amount: useId() };
  const [payRef, setPayRef] = useState("");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");
  const [error, setError] = useState("");

  async function run() {
    setError("");
    setResult("");
    const ref = payRef.trim().toUpperCase().replace(/[\s-]/g, "");
    const amt = Number(amount);
    if (!/^BK\d{11}$/.test(ref)) return setError("Nội dung CK dạng BK + 11 chữ số, ví dụ BK20261029001.");
    if (!Number.isInteger(amt) || amt <= 0) return setError("Số tiền phải là số nguyên lớn hơn 0.");
    setBusy(true);
    try {
      const res = await write((key) => sendSimulate(key, ref, amt));
      if (!res.ok) return setError(errorText(res.error));
      const t = res.data;
      const extra =
        t.outcome === "applied" && t.booking_codes.length
          ? ` · Đã tạo booking ${t.booking_codes.join(", ")}`
          : t.refund_amount > 0
            ? ` · Cần hoàn ${formatVnd(t.refund_amount)}`
            : "";
      setResult(`${OUTCOME_TEXT[t.outcome]}${extra}`);
      void onDone();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Giả lập tiền về (chỉ môi trường thử)">
      <p className="mb-3 text-sm text-muted">Giả lập một giao dịch ngân hàng đi đúng đường xử lý của webhook SePay. Khối này không có ở production.</p>
      <div className="grid gap-3 sm:grid-cols-[1fr_12rem_auto] sm:items-end">
        <div>
          <label htmlFor={ids.ref} className="mb-1 block text-sm font-medium">
            Nội dung CK
          </label>
          <input id={ids.ref} value={payRef} placeholder="BK20261029001" autoComplete="off" onChange={(e) => setPayRef(e.target.value)} className={inputCls} />
        </div>
        <div>
          <label htmlFor={ids.amount} className="mb-1 block text-sm font-medium">
            Số tiền
          </label>
          <input id={ids.amount} value={amount} inputMode="numeric" placeholder="288000" onChange={(e) => setAmount(e.target.value.replace(/\D/g, ""))} className={inputCls} />
        </div>
        <button type="button" onClick={run} disabled={busy} className={btnPrimaryCls}>
          {busy ? "Đang gửi…" : "Giả lập"}
        </button>
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error}
        </p>
      ) : null}
      {result ? (
        <p role="status" className="mt-3 rounded-md bg-free p-3 text-sm font-medium">
          {result}
        </p>
      ) : null}
    </Card>
  );
}
