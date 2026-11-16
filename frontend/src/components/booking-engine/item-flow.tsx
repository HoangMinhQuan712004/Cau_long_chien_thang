"use client";

import { useCallback, useEffect, useId, useState } from "react";
import { CopyIcon } from "@/components/ui/icons";
import { Modal } from "@/components/ui/modal";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { cn } from "@/lib/cn";
import { formatDateTime, formatDayMonth, formatDayMonthYear, formatLongDate, formatVnd, hhmm } from "@/lib/format";
import { formatPhone } from "@/lib/phone";
import { authFailure } from "./booking-dialogs";
import { CollectQrDialog } from "./collect-qr";
import { MoveDialog } from "./move-dialog";
import { MoveHistory } from "./move-history";
import { getItem, sendCancelItem, sendCollect, sendUncollectible } from "./requests";
import type { Item } from "./types";
import {
  btnCls,
  btnDangerCls,
  btnPrimaryCls,
  btnRowCls,
  ErrorBanner,
  Group,
  METHOD_LABEL,
  raisedFooterCls,
  resourceLabels,
  STATUS_LABEL,
  STATUS_TONE,
  textareaCls,
} from "./ui";

// Luồng một booking / vé: Thông tin → Thu tiền | Không thu được | Hủy (T-051, chỉ Admin) | Đổi sân (move-dialog). Dùng ở màn Đặt sân, Đơn đặt sân và Lịch sử giao dịch.
// Thông tin: cấu trúc như dev (Mã đơn / Mã khối, nhóm KHÁCH ĐẶT · LỊCH ĐẶT · THANH TOÁN). Dưới md dọc (điện thoại: bảng trượt
// từ đáy); từ md ngang 896px: hàng mã + số tiền / trạng thái, dưới là 3 cột nhóm. Chân chỉ khi có thao tác, nút rộng bằng nhau.

type Props = {
  code: string;
  onClose: () => void;
  /** Đã ghi thay đổi (thu tiền / Không thu được) hoặc phát hiện dữ liệu đổi: cha tải lại lịch / danh sách. */
  onChanged: () => void;
  /** Mở popup Sự kiện từ dòng "Sự kiện" của vé (tùy chọn). */
  onOpenSession?: (code: string) => void;
  /** Mở cả đơn (danh sách khối + Thu cả đơn) từ dòng "Mã đơn" (T-019). */
  onOpenOrder?: (orderCode: string) => void;
  /** T-068: mở thẳng bước Thu tiền (nút "Thu tiền" trên dòng vé ở popup Sự kiện); không thu được thì về Thông tin. */
  startCollect?: boolean;
};

type Step = "info" | "collect" | "bad" | "cancel" | "move";

export function ItemFlow({ code, onClose, onChanged, onOpenSession, onOpenOrder, startCollect = false }: Props) {
  const [item, setItem] = useState<Item | null>(null);
  const [error, setError] = useState("");
  const [step, setStep] = useState<Step>(startCollect ? "collect" : "info");

  const load = useCallback(async () => {
    const res = await getItem(code);
    if (res.ok) {
      setItem(res.data);
      setError("");
    } else {
      setError(errorText(res.error));
    }
  }, [code]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải dữ liệu khi mở hộp thoại
    void load();
  }, [load]);

  /** Dữ liệu đổi ở máy khác (E-012): báo, tải lại bản mới, quay về Thông tin. */
  async function onStale(message: string) {
    toast(message, undefined, "error");
    await load();
    setStep("info");
    onChanged();
  }

  if (!item) {
    return (
      <Modal open sheet size="medium" onClose={onClose} title="Thông tin">
        {error ? <ErrorBanner>{error}</ErrorBanner> : <p className="text-sm text-muted" role="status">Đang tải…</p>}
      </Modal>
    );
  }
  if (step === "collect" && item.actions.includes("collect")) {
    // T-065 / T-068: booking quầy và vé quầy thu bằng QR riêng (mã con / mã vé bỏ gạch), có nút tiền mặt + Không thu được
    if ((item.kind === "booking" && item.order_code) || (item.kind === "ticket" && item.source === "counter")) {
      return <CollectItemQr item={item} onBack={() => setStep("info")} onBad={() => setStep("bad")} onClose={onClose} onDone={onChanged} onStale={onStale} />;
    }
    return <CollectDialog item={item} onBack={() => setStep("info")} onClose={onClose} onDone={onChanged} onStale={onStale} />;
  }
  if (step === "bad") {
    return <UncollectibleDialog item={item} onBack={() => setStep("info")} onClose={onClose} onDone={onChanged} onStale={onStale} />;
  }
  if (step === "cancel") {
    return <CancelDialog item={item} onBack={() => setStep("info")} onClose={onClose} onDone={onChanged} onStale={onStale} />;
  }
  if (step === "move") {
    const onMoved = (next: Item) => {
      setItem(next);
      setStep("info");
      onChanged();
    };
    return <MoveDialog item={item} court={courtTitle(item)} when={whenLine(item)} onBack={() => setStep("info")} onClose={onClose} onMoved={onMoved} onStale={onStale} />;
  }
  return <InfoDialog item={item} onClose={onClose} onCollect={() => setStep("collect")} onBad={() => setStep("bad")} onCancel={() => setStep("cancel")} onMove={() => setStep("move")} onOpenSession={onOpenSession} onOpenOrder={onOpenOrder} />;
}

/** Tiêu đề popup = sân ("S01 · Sân 1"); dòng phụ = ngày · giờ · số giờ. */
const courtTitle = (item: Item) => resourceLabels(item.schedule.resource_codes, item.schedule.resource_names);
function whenLine(item: Item) {
  const s = item.schedule;
  const hours = Number(hhmm(s.end_time).slice(0, 2)) - Number(hhmm(s.start_time).slice(0, 2));
  return `${formatLongDate(s.play_date)} · ${hhmm(s.start_time)}–${hhmm(s.end_time)}${hours > 0 ? ` · ${hours} giờ` : ""}`;
}

/** Hàng điểm nhìn: badge trạng thái bên trái, số tiền 2xl bên phải (dùng chung Thông tin / Thu tiền / Không thu được). */
function StatusAmount({ item }: { item: Item }) {
  const p = item.payment;
  return (
    <div className="flex items-center justify-between gap-3">
      <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-sm font-semibold", STATUS_TONE[p.payment_status])}>
        <span aria-hidden className="size-1.5 rounded-full bg-current" />
        {STATUS_LABEL[p.payment_status]}
      </span>
      <p className="text-2xl font-bold tabular-nums">{formatVnd(p.amount)}</p>
    </div>
  );
}

/** Khách: tên đậm + badge loại hồ sơ / hạng; SĐT là link gọi (tel:). */
function CustomerBlock({ item }: { item: Item }) {
  const c = item.customer;
  return (
    <div className="space-y-0.5">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-semibold">{c.name}</span>
        <span className="rounded-full bg-background px-2 py-0.5 text-xs text-muted">{c.profile_label}</span>
        </p>
      {c.phone ? (
        <a href={`tel:${c.phone}`} className="inline-flex min-h-8 items-center text-sm text-primary tabular-nums hover:underline focus-ring">
          {formatPhone(c.phone)}
        </a>
      ) : (
        <p className="text-sm text-muted">Không có SĐT</p>
      )}
    </div>
  );
}

/** Nút chép mã: icon 16px trong vùng chạm 32px; toast như cũ. */
function CopyButton({ code }: { code: string }) {
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      toast(`Đã chép ${code}`, undefined, "info");
    } catch {
      toast("Không chép được, hãy chọn và sao chép tay", undefined, "error");
    }
  };
  return (
    <button type="button" onClick={() => void copy()} title="Chép mã" aria-label={`Chép mã ${code}`} className="grid size-8 shrink-0 place-items-center rounded-md text-muted hover:bg-primary-softer hover:text-primary focus-ring">
      <CopyIcon size={16} />
    </button>
  );
}

/** Danh sách nhãn trái / giá trị phải như dev (Kv), làm đẹp nhẹ: nhãn muted cột cố định, giá trị thẳng cột, xuống dòng theo từ. */
/** Dòng [nhãn, giá trị, chỉ hiện dưới md?] – dòng `true` ẩn từ md vì đã lên hàng đầu của bố cục ngang. */
type KvRow = [string, React.ReactNode, boolean?];

function KvList({ rows }: { rows: KvRow[] }) {
  return (
    <dl className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-center gap-x-3 sm:grid-cols-[8rem_minmax(0,1fr)] md:grid-cols-[5.5rem_minmax(0,1fr)]">
      {rows.map(([k, v, narrowOnly]) => (
        <div key={k} className={narrowOnly ? "contents md:hidden" : "contents"}>
          <dt className="py-1 text-ui text-muted">{k}</dt>
          <dd className="flex min-h-8 min-w-0 flex-wrap items-center gap-x-1 py-1 text-sm break-words">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

const nowrap = (text: string) => <span className="whitespace-nowrap">{text}</span>;
/** "a · b" một dòng (dưới md); từ md (cột hẹp) tách thành 2 dòng có chủ đích, bỏ dấu "·". */
const twoLines = (a: string, b: string) => (
  <span className="tabular-nums">
    {nowrap(a)}
    <span className="md:hidden"> · </span>
    <br className="hidden md:block" />
    {nowrap(b)}
  </span>
);

// Bố cục đúng như dev: hàng Mã đơn / Mã khối, rồi 3 nhóm KHÁCH ĐẶT · LỊCH ĐẶT · THANH TOÁN (Group của dev); chỉ làm đẹp nhẹ
function InfoDialog({
  item,
  onClose,
  onCollect,
  onBad,
  onCancel,
  onMove,
  onOpenSession,
  onOpenOrder,
}: {
  item: Item;
  onClose: () => void;
  onCollect: () => void;
  onBad: () => void;
  onCancel: () => void;
  onMove: () => void;
  onOpenSession?: (code: string) => void;
  onOpenOrder?: (orderCode: string) => void;
}) {
  const isTicket = item.kind === "ticket";
  const p = item.payment;
  const s = item.schedule;
  const c = item.customer;
  const status = p.payment_status;
  const canCollect = item.actions.includes("collect");
  const canBad = item.actions.includes("uncollectible");
  const canMove = item.actions.includes("move"); // booking một sân, chưa kết thúc; BE quyết
  const canCancel = item.actions.includes("cancel"); // chỉ Admin, buổi chưa bắt đầu, chưa hủy (T-051 AC1)
  const mono = (code: string) => <span className="font-mono text-ui">{code}</span>;

  const booking: KvRow[] = [];
  if (isTicket || !item.order_code) {
    booking.push([isTicket ? "Mã check-in" : "Mã booking", <>{mono(item.code)}<CopyButton code={item.code} /></>]);
  } else {
    const order = item.order_code;
    booking.push([
      "Mã đơn",
      <>
        {onOpenOrder ? (
          <button type="button" onClick={() => onOpenOrder(order)} title="Xem cả đơn" className="rounded font-mono text-ui text-primary hover:underline focus-ring">
            {order}
          </button>
        ) : (
          mono(order)
        )}
        <CopyButton code={order} />
      </>,
    ]);
    booking.push(["Mã khối", <>{mono(item.code)}<CopyButton code={item.code} /></>]);
  }
  const customer: KvRow[] = [];
  customer.push(["Tên", <span key="t" className="font-medium">{c.name}</span>]);
  customer.push([
    "SĐT",
    c.phone ? (
      <a key="p" href={`tel:${c.phone}`} className="text-primary tabular-nums hover:underline focus-ring">
        {formatPhone(c.phone)}
      </a>
    ) : (
      "—"
    ),
  ]);
  // Hạng đã nằm trong profile_label ("Hội viên (HV0012 · Hạng Khá)") ⇒ không thêm badge hạng
  customer.push(["Loại hồ sơ", c.profile_label]);
  const schedule: KvRow[] = [];
  schedule.push(["Mã sân", s.resource_codes.join(", ")]);
  schedule.push(["Sân", s.resource_names.join(", ")]);
  schedule.push(["Ngày / giờ", twoLines(formatDayMonthYear(s.play_date), `${hhmm(s.start_time)} – ${hhmm(s.end_time)}`)]);
  if (s.session) {
    const session = s.session;
    schedule.push([
      "Sự kiện",
      onOpenSession ? (
        <button type="button" onClick={() => onOpenSession(session.code)} className="text-left text-primary hover:underline focus-ring">
          {session.name} ({session.code})
        </button>
      ) : (
        `${session.name} (${session.code})`
      ),
    ]);
  }
  if (item.note) schedule.push(["Ghi chú", item.note]);

  const amount = <span className="text-lg font-semibold tabular-nums md:text-2xl md:font-bold">{formatVnd(p.amount)}</span>;
  const badge = <span className={cn("rounded-full px-2 py-0.5 text-xs font-semibold", STATUS_TONE[status])}>{STATUS_LABEL[status]}</span>;
  const payment: KvRow[] = [
    ["Số tiền", amount, true],
    ["Trạng thái", badge, true],
  ];
  const wasPaid = status === "paid" || (status === "cancelled" && Boolean(p.paid_at)); // khoản đã hủy vẫn giữ dấu vết lần thu
  if (wasPaid) {
    payment.push(["Phương thức", p.payment_method ? METHOD_LABEL[p.payment_method] : "—"]);
    payment.push(["Thời gian TT", p.paid_at ? nowrap(formatDateTime(p.paid_at)) : "—"]);
  }
  payment.push(["Người tạo", twoLines(item.created_by, formatDateTime(item.created_at))]);
  if (wasPaid) payment.push(["Người thu", nowrap(p.collected_by ?? "—")]);
  if (status === "uncollectible") {
    payment.push(["Lý do", p.uncollectible_reason ?? "—"]);
    payment.push(["Người đánh dấu", p.marked_at ? twoLines(p.marked_by ?? "—", formatDateTime(p.marked_at)) : nowrap(p.marked_by ?? "—")]);
  }
  if (status === "cancelled") {
    payment.push(["Lý do hủy", p.cancel_reason ?? "—"]);
    payment.push(["Người hủy", p.cancelled_at ? twoLines(p.cancelled_by_label ?? "—", formatDateTime(p.cancelled_at)) : nowrap(p.cancelled_by_label ?? "—")]);
    if (wasPaid) payment.push(["Đã hoàn", (p.refund_amount ?? 0) > 0 ? <span className="font-semibold tabular-nums">{formatVnd(p.refund_amount ?? 0)}</span> : "—"]);
  }

  return (
    <Modal
      open
      sheet
      size="large"
      onClose={onClose}
      title={isTicket ? "Thông tin vé" : "Thông tin booking"}
      footerClassName={raisedFooterCls}
      // Chỉ khi có thao tác: nút rộng bằng nhau (điện thoại chia đôi, dính đáy); không có ⇒ chỉ nút ×
      footer={
        canCollect || canBad || canCancel || canMove ? (
          <div className="flex w-full flex-col gap-2 sm:flex-row sm:items-center">
            {canCancel || canMove ? (
              // Nhóm trái: Hủy + Đổi sân sát nhau (gap 8px), rộng theo chữ; điện thoại chia đôi hàng
              <div className={cn(btnRowCls, canCancel && canMove ? "grid-cols-2" : "grid-cols-1", "sm:mr-auto sm:flex sm:w-auto")}>
                {canCancel ? (
                  <button type="button" onClick={onCancel} className={cn(btnCls, "border-danger text-danger enabled:hover:bg-danger/10")}>
                    {isTicket ? "Hủy vé" : "Hủy booking"}
                  </button>
                ) : null}
                {canMove ? (
                  <button type="button" onClick={onMove} className={btnCls}>
                    Đổi sân
                  </button>
                ) : null}
              </div>
            ) : null}
            {canCollect || canBad ? (
              <div className={cn(btnRowCls, canCollect && canBad ? "grid-cols-2 md:w-96" : "grid-cols-1 sm:w-1/2 md:w-48", !canCancel && !canMove && "sm:ml-auto")}>
                {canBad ? (
                  <button type="button" onClick={onBad} className={cn(btnCls, "border-danger text-danger enabled:hover:bg-danger/10")}>
                    Không thu được
                  </button>
                ) : null}
                {canCollect ? (
                  <button type="button" onClick={onCollect} className={cn(btnPrimaryCls, "whitespace-nowrap")}>
                    Thu tiền · {formatVnd(p.amount)}
                  </button>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : undefined
      }
    >
      {/* Dưới md: dọc như dev. Từ md: hàng đầu = các mã (ngang) + số tiền lớn & trạng thái bên phải; dưới là 3 cột nhóm */}
      <div className="md:flex md:items-center md:justify-between md:gap-6">
        <div className="md:hidden">
          <KvList rows={booking} />
        </div>
        <p className="hidden flex-wrap items-center gap-x-5 gap-y-1 md:flex">
          {booking.map(([k, v]) => (
            <span key={k} className="inline-flex items-center gap-1.5">
              <span className="text-ui text-muted">{k}</span>
              {v}
            </span>
          ))}
        </p>
        <div className="hidden shrink-0 items-center gap-3 md:flex">
          {badge}
          {amount}
        </div>
      </div>
      <div className="space-y-4 md:grid md:grid-cols-3 md:space-y-0 md:divide-x md:divide-border [&>section]:md:px-4 [&>section]:md:first:pl-0 [&>section]:md:last:pr-0">
        <Group title="Khách đặt">
          <KvList rows={customer} />
        </Group>
        <Group title="Lịch đặt">
          <KvList rows={schedule} />
        </Group>
        <Group title="Thanh toán">
          <KvList rows={payment} />
        </Group>
      </div>
      {/* Khu riêng rộng hết popup, dưới 3 cột; chưa đổi sân lần nào thì không có */}
      <MoveHistory item={item} />
    </Modal>
  );
}

type StepProps = {
  item: Item;
  onBack: () => void;
  onClose: () => void;
  onDone: () => void;
  onStale: (message: string) => Promise<void>;
};

/** Thu tiền một buổi (T-065): popup QR dùng chung với Thu cả đơn; bước tiền mặt gọi thu từng buổi như CollectDialog. */
function CollectItemQr({ item, onBack, onBad, onClose, onDone, onStale }: StepProps & { onBad: () => void }) {
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");

  async function cash() {
    if (busy) return;
    setBusy(true);
    setBanner("");
    try {
      const res = await write((key) => sendCollect(key, item.code, "cash", item.version));
      if (!res.ok) {
        const e = res.error;
        if (authFailure(e)) return;
        if (e.code === "E-012") return void (await onStale(errorText(e)));
        setBanner(errorText(e));
        return;
      }
      toast(`Đã thu ${formatVnd(item.payment.amount)} · ${item.code}`, "Tiền mặt · trạng thái chuyển sang Đã thanh toán");
      onDone();
      onClose();
    } finally {
      setBusy(false);
    }
  }

  return (
    <CollectQrDialog
      orderCode={item.order_code ?? item.code /* vé: mã vé */}
      item={{ code: item.code, bad: { enabled: item.actions.includes("uncollectible"), onClick: onBad } }}
      busy={busy}
      banner={banner}
      onClose={onClose}
      onBack={onBack}
      onConfirmCash={() => void cash()}
      onPaid={() => {
        onDone();
        onClose();
      }}
      cashBody={
        <>
          <StatusAmount item={item} />
          <CustomerBlock item={item} />
        </>
      }
    />
  );
}

function CollectDialog({ item, onBack, onClose, onDone, onStale }: StepProps) {
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");

  async function confirm() {
    setBusy(true);
    setBanner("");
    try {
      // Lựa chọn Chuyển khoản ẩn cho tới T-007 (cổng thanh toán); hiện chỉ thu tiền mặt.
      const res = await write((key) => sendCollect(key, item.code, "cash", item.version));
      if (!res.ok) {
        const e = res.error;
        if (authFailure(e)) return;
        if (e.code === "E-012") return void (await onStale(errorText(e)));
        setBanner(errorText(e));
        return;
      }
      toast(
        `Đã thu ${formatVnd(item.payment.amount)} · ${item.schedule.resource_codes.join(", ")} · ${item.schedule.resource_names.join(", ")} · ${hhmm(item.schedule.start_time)}–${hhmm(item.schedule.end_time)}`,
        "Tiền mặt · trạng thái chuyển sang Đã thanh toán",
      );
      onDone();
      onClose();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      sheet
      size="medium"
      title="Thu tiền"
      subtitle={`${courtTitle(item)} · ${whenLine(item)}`}
      footerClassName={raisedFooterCls}
      footer={
        <div className={cn(btnRowCls, "grid-cols-2")}>
          <button type="button" onClick={onBack} disabled={busy} className={btnCls}>
            Hủy
          </button>
          <button type="button" onClick={confirm} disabled={busy} className={cn(btnPrimaryCls, "whitespace-nowrap")}>
            {busy ? "Đang lưu…" : "Xác nhận đã thu"}
          </button>
        </div>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      <StatusAmount item={item} />
      <CustomerBlock item={item} />
      <fieldset>
        <legend className="mb-1 text-xs font-semibold tracking-wide text-muted uppercase">Phương thức</legend>
        <label className="flex min-h-10 items-center gap-2 text-sm">
          <input type="radio" name="pay-method" checked readOnly className="size-4 accent-primary" />
          Tiền mặt
        </label>
      </fieldset>
    </Modal>
  );
}

function UncollectibleDialog({ item, onBack, onClose, onDone, onStale }: StepProps) {
  const reasonId = useId();
  const [reason, setReason] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");
  const err = !reason.trim() ? "Vui lòng nhập Lý do." : "";
  const noun = item.kind === "ticket" ? "Vé" : "Booking";

  async function confirm() {
    setSubmitted(true);
    setBanner("");
    if (err) return;
    setBusy(true);
    try {
      const res = await write((key) => sendUncollectible(key, item.code, reason.trim(), item.version));
      if (!res.ok) {
        const e = res.error;
        if (authFailure(e)) return;
        if (e.code === "E-012") return void (await onStale(errorText(e)));
        setBanner(errorText(e));
        return;
      }
      toast(`Đã đánh dấu Không thu được · ${item.code}`, `${noun} không tính vào doanh thu`);
      onDone();
      onClose();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      sheet
      size="medium"
      title="Không thu được"
      subtitle={`${courtTitle(item)} · ${whenLine(item)}`}
      footerClassName={raisedFooterCls}
      footer={
        <div className={cn(btnRowCls, "grid-cols-2")}>
          <button type="button" onClick={onBack} disabled={busy} className={btnCls}>
            Hủy
          </button>
          <button type="button" onClick={confirm} disabled={busy} className={btnDangerCls}>
            {busy ? "Đang lưu…" : "Xác nhận Không thu được"}
          </button>
        </div>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      <StatusAmount item={item} />
      <CustomerBlock item={item} />
      <div>
        <label htmlFor={reasonId} className="mb-1.5 block text-label font-semibold text-muted">
          Lý do <span className="text-danger">*</span>
        </label>
        <textarea
          id={reasonId}
          value={reason}
          maxLength={200}
          placeholder="Khách về trước khi thanh toán, không liên lạc được"
          onChange={(e) => setReason(e.target.value)}
          aria-invalid={Boolean(submitted && err) || undefined}
          className={`${textareaCls} min-h-20`}
        />
        <div className="mt-1 flex text-xs">
          {submitted && err ? <span className="text-danger">{err}</span> : null}
          <span className="ml-auto text-muted">{reason.length} / 200</span>
        </div>
      </div>
      <ErrorBanner>
        {noun} chuyển sang Không thu được, không tính vào doanh thu và không thu tiền lại được.{" "}
        {item.kind === "ticket" ? "Chỗ của vé vẫn được tính, số chỗ không giảm." : "Khung vẫn giữ trên lịch, không bán lại."} Thao tác được ghi vào Lịch sử thao tác.
      </ErrorBanner>
    </Modal>
  );
}

/** Hủy booking / vé (T-051, ADR-013): chỉ trừ số liệu, Admin tự hoàn tiền cho khách. Lý do bắt buộc; đã thu thì phải tick xác nhận hoàn tiền. */
function CancelDialog({ item, onBack, onClose, onDone, onStale }: StepProps) {
  const reasonId = useId();
  const refundId = useId();
  const [reason, setReason] = useState("");
  const [refunded, setRefunded] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");
  const isTicket = item.kind === "ticket";
  const noun = isTicket ? "vé" : "booking";
  const amount = item.payment.amount;
  const collected = item.payment.payment_status === "paid";
  const phase = item.cancel_phase ?? "before"; // T-052: câu cảnh báo theo giai đoạn của buổi
  const playDay = formatDayMonth(item.schedule.play_date);
  const errs = {
    reason: !reason.trim() ? "Vui lòng nhập Lý do." : reason.trim().length > 200 ? "Lý do tối đa 200 ký tự." : "",
    refund: collected && !refunded ? "Vui lòng xác nhận việc hoàn tiền cho khách." : "",
  };

  async function confirm() {
    setSubmitted(true);
    setBanner("");
    if (errs.reason || errs.refund) return;
    setBusy(true);
    try {
      const res = await write((key) => sendCancelItem(key, item.code, { reason: reason.trim(), version: item.version, refund_confirmed: refunded }));
      if (!res.ok) {
        const e = res.error;
        if (authFailure(e)) return;
        // Dữ liệu đổi ở nơi khác (E-012), đã bắt đầu mà chưa thu (E-PAY-5) hoặc đã hủy / Không thu được (E-PAY-6): tải lại bản mới
        if (e.code === "E-012" || e.code === "E-PAY-5" || e.code === "E-PAY-6") return void (await onStale(errorText(e)));
        setBanner(errorText(e));
        return;
      }
      toast(`Đã hủy ${noun} · ${item.code}`, collected ? `Đã trừ ${formatVnd(amount)} khỏi doanh thu${phase === "past" ? ` ngày ${playDay}` : ""}` : "Khung đã trống lại");
      onDone();
      onClose();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      sheet
      size="medium"
      title={isTicket ? "Hủy vé" : "Hủy booking"}
      subtitle={`${courtTitle(item)} · ${whenLine(item)}`}
      footerClassName={raisedFooterCls}
      footer={
        <div className={cn(btnRowCls, "grid-cols-2")}>
          <button type="button" onClick={onBack} disabled={busy} className={btnCls}>
            Quay lại
          </button>
          <button type="button" onClick={confirm} disabled={busy} className={cn(btnDangerCls, "whitespace-nowrap")}>
            {busy ? "Đang hủy…" : `Xác nhận hủy ${noun}`}
          </button>
        </div>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      <StatusAmount item={item} />
      <CustomerBlock item={item} />
      <p className="text-sm text-muted">
        Mã {isTicket ? "vé" : "booking"}: <span className="font-mono text-ui text-foreground">{item.code}</span>
      </p>
      <div>
        <label htmlFor={reasonId} className="mb-1.5 block text-label font-semibold text-muted">
          Lý do <span className="text-danger">*</span>
        </label>
        <textarea
          id={reasonId}
          value={reason}
          maxLength={200}
          placeholder="Khách báo không đến được, trùng lịch"
          onChange={(e) => setReason(e.target.value)}
          aria-invalid={Boolean(submitted && errs.reason) || undefined}
          className={`${textareaCls} min-h-20`}
        />
        <div className="mt-1 flex text-xs">
          {submitted && errs.reason ? <span className="text-danger">{errs.reason}</span> : null}
          <span className="ml-auto text-muted">{reason.length} / 200</span>
        </div>
      </div>
      {collected ? (
        <div className="space-y-2">
          {phase === "playing" ? (
            <ErrorBanner>
              {isTicket
                ? "Buổi đang diễn ra. Chỗ của vé được trả lại ngay. Hãy báo người đang trên sân."
                : "Buổi đang diễn ra. Khung giờ sẽ trống ngay và phòng chơi đóng lại. Hãy báo người đang trên sân."}
            </ErrorBanner>
          ) : null}
          <ErrorBanner>
            {phase === "past" ? (
              <>
                Buổi đã chơi ngày {playDay}. Chỉ trừ <b>{formatVnd(amount)}</b> khỏi doanh thu ngày đó.
              </>
            ) : (
              <>
                Sẽ trừ <b>{formatVnd(amount)}</b> khỏi doanh thu.
              </>
            )}{" "}
            Hệ thống không tự hoàn tiền, bạn tự trả cho khách.
          </ErrorBanner>
          <label htmlFor={refundId} className="flex min-h-11 cursor-pointer items-start gap-2 text-sm">
            <input id={refundId} type="checkbox" checked={refunded} onChange={(e) => setRefunded(e.target.checked)} aria-invalid={Boolean(submitted && errs.refund) || undefined} className="mt-0.5 size-5 shrink-0 accent-primary" />
            <span>
              Tôi đã hoàn / sẽ tự hoàn tiền cho khách <span className="text-danger">*</span>
              {submitted && errs.refund ? <span className="block text-xs text-danger">{errs.refund}</span> : null}
            </span>
          </label>
        </div>
      ) : null}
      <p className="text-xs text-muted">
        {item.customer.kind === "member"
          ? "Hội viên có tài khoản sẽ nhận thông báo (không kèm lý do). Nếu khách chưa có tài khoản, hãy tự báo khách."
          : "Khách không có tài khoản nên không nhận được thông báo nào, hãy tự báo khách."}
      </p>
    </Modal>
  );
}
