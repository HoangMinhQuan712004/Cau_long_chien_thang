"use client";

import { useCallback, useEffect, useId, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatDateTime, formatDayMonthYear, formatVnd, hhmm } from "@/lib/format";
import { formatPhone } from "@/lib/phone";
import { authFailure } from "./booking-dialogs";
import { getItem, sendCollect, sendUncollectible } from "./requests";
import type { Item } from "./types";
import {
  btnCls,
  btnDangerCls,
  btnDangerOutlineCls,
  btnPrimaryCls,
  ErrorBanner,
  Group,
  inputCls,
  Kv,
  METHOD_LABEL,
  resourceLabels,
  StatusBadge,
  SummaryBox,
} from "./ui";

// Luồng một booking / vé: Thông tin → Thu tiền | Không thu được. Dùng ở màn Đặt sân và Lịch sử giao dịch.

type Props = {
  code: string;
  onClose: () => void;
  /** Đã ghi thay đổi (thu tiền / Không thu được) hoặc phát hiện dữ liệu đổi: cha tải lại lịch / danh sách. */
  onChanged: () => void;
  /** Mở popup Sự kiện từ dòng "Sự kiện" của vé (tùy chọn). */
  onOpenSession?: (code: string) => void;
  /** Mở cả đơn (danh sách khối + Thu cả đơn) từ dòng "Mã đơn" (T-019). */
  onOpenOrder?: (orderCode: string) => void;
};

type Step = "info" | "collect" | "bad";

export function ItemFlow({ code, onClose, onChanged, onOpenSession, onOpenOrder }: Props) {
  const [item, setItem] = useState<Item | null>(null);
  const [error, setError] = useState("");
  const [step, setStep] = useState<Step>("info");

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
      <Modal open onClose={onClose} title="Thông tin" footer={<button type="button" onClick={onClose} className={btnCls}>Đóng</button>}>
        {error ? <ErrorBanner>{error}</ErrorBanner> : <p className="text-sm text-muted">Đang tải…</p>}
      </Modal>
    );
  }
  if (step === "collect") {
    return <CollectDialog item={item} onBack={() => setStep("info")} onClose={onClose} onDone={onChanged} onStale={onStale} />;
  }
  if (step === "bad") {
    return <UncollectibleDialog item={item} onBack={() => setStep("info")} onClose={onClose} onDone={onChanged} onStale={onStale} />;
  }
  return <InfoDialog item={item} onClose={onClose} onCollect={() => setStep("collect")} onBad={() => setStep("bad")} onOpenSession={onOpenSession} onOpenOrder={onOpenOrder} />;
}

const when = (item: Item) =>
  `${formatDayMonthYear(item.schedule.play_date)} · ${hhmm(item.schedule.start_time)} – ${hhmm(item.schedule.end_time)}`;

function InfoDialog({
  item,
  onClose,
  onCollect,
  onBad,
  onOpenSession,
  onOpenOrder,
}: {
  item: Item;
  onClose: () => void;
  onCollect: () => void;
  onBad: () => void;
  onOpenSession?: (code: string) => void;
  onOpenOrder?: (orderCode: string) => void;
}) {
  const isTicket = item.kind === "ticket";
  const p = item.payment;
  const s = item.schedule;
  const status = p.payment_status;

  const schedule: [string, React.ReactNode][] = [
    ["Mã sân", s.resource_codes.join(", ")],
    ["Sân", s.resource_names.join(", ")],
    ["Ngày / giờ", when(item)],
  ];
  if (s.session) {
    schedule.push([
      "Sự kiện",
      onOpenSession ? (
        <button type="button" onClick={() => onOpenSession(s.session!.code)} className="text-primary hover:underline">
          {s.session.name} ({s.session.code})
        </button>
      ) : (
        `${s.session.name} (${s.session.code})`
      ),
    ]);
  }
  if (item.note) schedule.push(["Ghi chú", item.note]);

  const payment: [string, React.ReactNode][] = [
    ["Số tiền", formatVnd(p.amount)],
    ["Trạng thái", <StatusBadge key="st" status={status} />],
  ];
  if (status === "paid") {
    payment.push(["Phương thức", p.payment_method ? METHOD_LABEL[p.payment_method] : "—"]);
    payment.push(["Thời gian TT", p.paid_at ? formatDateTime(p.paid_at) : "—"]);
  }
  payment.push(["Người tạo", `${item.created_by} · ${formatDateTime(item.created_at)}`]);
  if (status === "paid") payment.push(["Người thu", p.collected_by ?? "—"]);
  if (status === "uncollectible") {
    payment.push(["Lý do", p.uncollectible_reason ?? "—"]);
    payment.push(["Người đánh dấu", `${p.marked_by ?? "—"}${p.marked_at ? ` · ${formatDateTime(p.marked_at)}` : ""}`]);
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={isTicket ? "Thông tin vé" : "Thông tin booking"}
      footer={
        <>
          {item.actions.includes("uncollectible") ? (
            <button type="button" onClick={onBad} className={btnDangerOutlineCls}>
              Không thu được
            </button>
          ) : null}
          <button type="button" onClick={onClose} className={btnCls}>
            Đóng
          </button>
          {item.actions.includes("collect") ? (
            <button type="button" onClick={onCollect} className={btnPrimaryCls}>
              Thu tiền
            </button>
          ) : null}
        </>
      }
    >
      <Kv
        rows={
          isTicket || !item.order_code
            ? [[isTicket ? "Mã check-in" : "Mã booking", <span key="c" className="font-mono">{item.code}</span>]]
            : [
                [
                  "Mã đơn",
                  onOpenOrder ? (
                    <button key="o" type="button" onClick={() => onOpenOrder(item.order_code as string)} className="font-mono text-primary hover:underline" title="Xem cả đơn">
                      {item.order_code}
                    </button>
                  ) : (
                    <span key="o" className="font-mono">{item.order_code}</span>
                  ),
                ],
                ["Mã khối", <span key="c" className="font-mono">{item.code}</span>],
              ]
        }
      />
      <Group title="Khách đặt">
        <Kv
          rows={[
            ["Tên", item.customer.name],
            ["SĐT", item.customer.phone ? formatPhone(item.customer.phone) : "—"],
            ["Loại hồ sơ", item.customer.profile_label],
          ]}
        />
      </Group>
      <Group title="Lịch đặt">
        <Kv rows={schedule} />
      </Group>
      <Group title="Thanh toán">
        <Kv rows={payment} />
      </Group>
    </Modal>
  );
}

function ItemSummary({ item }: { item: Item }) {
  return (
    <SummaryBox>
      <p className="font-semibold">{item.code}</p>
      <p>
        {resourceLabels(item.schedule.resource_codes, item.schedule.resource_names)} · {hhmm(item.schedule.start_time)}–{hhmm(item.schedule.end_time)} ·{" "}
        {formatDayMonthYear(item.schedule.play_date)}
      </p>
      <p className="text-muted">{item.customer.name}</p>
    </SummaryBox>
  );
}

type StepProps = {
  item: Item;
  onBack: () => void;
  onClose: () => void;
  onDone: () => void;
  onStale: (message: string) => Promise<void>;
};

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
      title="Thu tiền"
      footer={
        <>
          <button type="button" onClick={onBack} disabled={busy} className={btnCls}>
            Hủy
          </button>
          <button type="button" onClick={confirm} disabled={busy} className={btnPrimaryCls}>
            {busy ? "Đang lưu…" : "Xác nhận đã thu"}
          </button>
        </>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      <ItemSummary item={item} />
      <div>
        <span className="mb-1 block text-sm font-medium">Số tiền phải thu</span>
        <p className="rounded-md border border-border bg-background px-3 py-2 text-sm font-semibold">{formatVnd(item.payment.amount)}</p>
      </div>
      <fieldset>
        <legend className="mb-1 text-sm font-medium">Phương thức</legend>
        <label className="flex items-center gap-2 text-sm">
          <input type="radio" name="pay-method" checked readOnly />
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
      title="Không thu được"
      footer={
        <>
          <button type="button" onClick={onBack} disabled={busy} className={btnCls}>
            Hủy
          </button>
          <button type="button" onClick={confirm} disabled={busy} className={btnDangerCls}>
            {busy ? "Đang lưu…" : "Xác nhận Không thu được"}
          </button>
        </>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      <ItemSummary item={item} />
      <div className="flex gap-3 text-sm">
        <span>Số tiền</span>
        <b className="ml-auto">{formatVnd(item.payment.amount)}</b>
      </div>
      <div>
        <label htmlFor={reasonId} className="mb-1 block text-sm font-medium">
          Lý do <span className="text-danger">*</span>
        </label>
        <textarea
          id={reasonId}
          value={reason}
          maxLength={200}
          placeholder="Khách về trước khi thanh toán, không liên lạc được"
          onChange={(e) => setReason(e.target.value)}
          aria-invalid={Boolean(submitted && err) || undefined}
          className={`${inputCls} min-h-20`}
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
