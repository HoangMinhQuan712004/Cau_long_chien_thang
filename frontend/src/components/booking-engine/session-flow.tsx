"use client";

import { useCallback, useEffect, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatDateTime, formatLongDate, formatVnd, hhmm } from "@/lib/format";
import { formatPhone } from "@/lib/phone";
import { authFailure, STALE_CODES } from "./booking-dialogs";
import { CustomerPicker, customerErrors, customerPayload, emptyCustomer, type CustomerErrors, type CustomerState } from "./customer-picker";
import { getSession, sendDeleteSession, sendTicket } from "./requests";
import type { Item, SessionDetail } from "./types";
import {
  btnCls,
  btnDangerCls,
  btnDangerOutlineCls,
  btnPrimaryCls,
  ErrorBanner,
  Group,
  Hint,
  Kv,
  resourceLabels,
  StatusBadge,
  SummaryBox,
} from "./ui";

// Luồng một sự kiện (buổi): Thông tin sự kiện → Đăng ký vé | Xóa buổi.

type Props = {
  code: string;
  onClose: () => void;
  /** Đã ghi thay đổi (đăng ký vé / xóa buổi) hoặc phát hiện dữ liệu đổi: cha tải lại lịch. */
  onChanged: () => void;
  /** Mở Thông tin vé khi bấm một dòng vé. */
  onOpenTicket: (code: string) => void;
};

type Step = "info" | "ticket" | "delete";

export function SessionFlow({ code, onClose, onChanged, onOpenTicket }: Props) {
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [error, setError] = useState("");
  const [step, setStep] = useState<Step>("info");
  const [nowMs, setNowMs] = useState(() => Date.now());

  const load = useCallback(async () => {
    const res = await getSession(code);
    if (res.ok) {
      setSession(res.data);
      setError("");
      setNowMs(Date.now());
    } else {
      setError(errorText(res.error));
    }
  }, [code]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải dữ liệu khi mở hộp thoại
    void load();
  }, [load]);

  // Đếm ngược chỗ đang giữ online
  const hasHold = (session?.active_holds.length ?? 0) > 0;
  useEffect(() => {
    if (!hasHold) return;
    const id = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(id);
  }, [hasHold]);

  async function backToInfo() {
    await load();
    setStep("info");
  }

  if (!session) {
    return (
      <Modal open onClose={onClose} title="Sự kiện" footer={<button type="button" onClick={onClose} className={btnCls}>Đóng</button>}>
        {error ? <ErrorBanner>{error}</ErrorBanner> : <p className="text-sm text-muted">Đang tải…</p>}
      </Modal>
    );
  }

  if (step === "ticket") {
    return (
      <TicketDialog
        session={session}
        onBack={backToInfo}
        onClose={onClose}
        onRegistered={async () => {
          onChanged();
          await backToInfo();
        }}
        onStale={async (message) => {
          toast(message, undefined, "error");
          onChanged();
          await backToInfo();
        }}
      />
    );
  }

  if (step === "delete") {
    return (
      <DeleteDialog
        session={session}
        onBack={() => setStep("info")}
        onClose={onClose}
        onDeleted={() => {
          onChanged();
          onClose();
        }}
        onStale={async (message) => {
          toast(message, undefined, "error");
          onChanged();
          await backToInfo();
        }}
      />
    );
  }

  const s = session;
  return (
    <Modal
      open
      onClose={onClose}
      size="wide"
      title={`Sự kiện · ${s.name}`}
      footer={
        <>
          {s.can.delete ? (
            <button type="button" onClick={() => setStep("delete")} className={btnDangerOutlineCls}>
              Xóa buổi
            </button>
          ) : null}
          <button type="button" onClick={onClose} className={btnCls}>
            Đóng
          </button>
          {s.can.register ? (
            <button type="button" onClick={() => setStep("ticket")} className={btnPrimaryCls}>
              Đăng ký vé
            </button>
          ) : null}
        </>
      }
    >
      <Kv
        rows={[
          ["Mã sự kiện", <span key="c" className="font-mono">{s.code}</span>],
          ["Ngày giờ", `${formatLongDate(s.play_date)} · ${hhmm(s.start_time)} – ${hhmm(s.end_time)}`],
          ["Sân", resourceLabels(s.resources.map((r) => r.code), s.resources.map((r) => r.name))],
          ["Giá vé", `${formatVnd(s.ticket_price)} / người`],
          [
            "Số chỗ",
            <span key="n">
              {s.taken}/{s.capacity}
              {s.is_full ? <span className="ml-2 rounded-full bg-danger/15 px-2 py-0.5 text-xs font-medium text-danger">Đủ chỗ</span> : null}
            </span>,
          ],
          ["Người tạo", `${s.created_by} · ${formatDateTime(s.created_at)}`],
        ]}
      />
      {s.active_holds.map((h) => {
        const left = Math.max(0, Math.floor((Date.parse(h.expires_at) - nowMs) / 1000));
        return (
          <p key={h.expires_at} className="rounded-md border border-dashed border-border px-3 py-2 text-sm text-muted">
            Đang giữ chỗ · {h.seats} chỗ · còn {String(Math.floor(left / 60)).padStart(2, "0")}:{String(left % 60).padStart(2, "0")}
          </p>
        );
      })}
      <Group title="Danh sách vé">
        {s.tickets.length ? (
          <div className="max-h-64 overflow-y-auto rounded-md border border-border">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted">
                <tr className="border-b border-border">
                  <th className="px-3 py-1.5 text-left font-medium">Mã check-in</th>
                  <th className="px-3 py-1.5 text-left font-medium">Khách</th>
                  <th className="px-3 py-1.5 text-left font-medium">SĐT</th>
                  <th className="px-3 py-1.5 text-left font-medium">Nguồn</th>
                  <th className="px-3 py-1.5 text-left font-medium">Trạng thái</th>
                </tr>
              </thead>
              <tbody>
                {s.tickets.map((t) => (
                  <tr key={t.code} className="border-b border-border last:border-0 hover:bg-primary-softer">
                    <td className="px-3 py-2 font-mono text-xs">
                      <button type="button" onClick={() => onOpenTicket(t.code)} className="text-primary hover:underline">
                        {t.code.slice(-3)}
                        <span className="sr-only"> — mở thông tin vé {t.code}</span>
                      </button>
                    </td>
                    <td className="px-3 py-2">{t.customer_name}</td>
                    <td className="px-3 py-2 whitespace-nowrap tabular-nums">{t.phone ? formatPhone(t.phone) : "—"}</td>
                    <td className="px-3 py-2">{t.source === "online" ? "Web" : "Quầy"}</td>
                    <td className="px-3 py-2">
                      <StatusBadge status={t.payment_status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="py-3 text-center text-sm text-muted">Chưa có người đăng ký.</p>
        )}
      </Group>
    </Modal>
  );
}

function TicketDialog({
  session,
  onBack,
  onClose,
  onRegistered,
  onStale,
}: {
  session: SessionDetail;
  onBack: () => void;
  onClose: () => void;
  onRegistered: () => Promise<void>;
  onStale: (message: string) => Promise<void>;
}) {
  const [customer, setCustomer] = useState<CustomerState>(emptyCustomer);
  const [serverErrors, setServerErrors] = useState<CustomerErrors>({});
  const [submitted, setSubmitted] = useState(false);
  const [banner, setBanner] = useState("");
  const [busy, setBusy] = useState(false);
  const s = session;
  const canSubmit = customer.mode === "temp" || customer.picked !== null;

  async function submit() {
    setSubmitted(true);
    setBanner("");
    setServerErrors({});
    const payload = customerPayload(customer);
    if (Object.keys(customerErrors(customer)).length || !payload) return;
    setBusy(true);
    try {
      const res = await write((key) => sendTicket(key, s.code, payload));
      if (!res.ok) {
        const e = res.error;
        if (authFailure(e)) return;
        if (e.code && STALE_CODES.includes(e.code)) return void (await onStale(errorText(e)));
        if (e.code === "E-018" || e.code === "E-002") setServerErrors({ phone: errorText(e) });
        else if (e.code === "E-014") setServerErrors({ pick: errorText(e) });
        else setBanner(errorText(e));
        return;
      }
      const ticket = res.data as Item;
      toast(`Đã đăng ký vé ${ticket.code} cho ${ticket.customer.name}`, "Trạng thái: Chưa thanh toán · thu tiền tại quầy");
      await onRegistered();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title="Đăng ký vé"
      footer={
        <>
          <button type="button" onClick={onBack} disabled={busy} className={btnCls}>
            Hủy
          </button>
          <button type="button" onClick={submit} disabled={busy || !canSubmit} className={btnPrimaryCls}>
            {busy ? "Đang đăng ký…" : "Đăng ký vé"}
          </button>
        </>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      <SummaryBox>
        <p className="font-semibold">Sự kiện · {s.name}</p>
        <p className="text-muted">
          {formatLongDate(s.play_date)} · {hhmm(s.start_time)} – {hhmm(s.end_time)} · {s.resources.map((r) => r.code).join(", ")}
        </p>
        <div className="flex gap-3 border-t border-border pt-1.5 font-semibold">
          <span>Giá vé</span>
          <span className="ml-auto tabular-nums">{formatVnd(s.ticket_price)}</span>
        </div>
        <p className="text-xs text-muted">
          Còn {Math.max(0, s.capacity - s.taken)} chỗ (đã đăng ký {s.taken}/{s.capacity})
        </p>
      </SummaryBox>
      <CustomerPicker state={customer} onChange={setCustomer} submitted={submitted} serverErrors={serverErrors} />
      <Hint>Khách trả tiền vé tại quầy — vé được tạo ở trạng thái Chưa thanh toán.</Hint>
    </Modal>
  );
}

function DeleteDialog({
  session,
  onBack,
  onClose,
  onDeleted,
  onStale,
}: {
  session: SessionDetail;
  onBack: () => void;
  onClose: () => void;
  onDeleted: () => void;
  onStale: (message: string) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState("");

  async function remove() {
    setBusy(true);
    setBanner("");
    try {
      const res = await write((key) => sendDeleteSession(key, session.code, session.version));
      if (!res.ok) {
        const e = res.error;
        if (authFailure(e)) return;
        if (e.code && STALE_CODES.includes(e.code)) return void (await onStale(errorText(e)));
        setBanner(errorText(e));
        return;
      }
      toast(`Đã xóa sự kiện "${session.name}"`, "Các khung đã trống lại");
      onDeleted();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title="Xóa sự kiện"
      footer={
        <>
          <button type="button" onClick={onBack} disabled={busy} className={btnCls}>
            Hủy
          </button>
          <button type="button" onClick={remove} disabled={busy} className={btnDangerCls}>
            {busy ? "Đang xóa…" : "Xóa buổi"}
          </button>
        </>
      }
    >
      {banner ? <ErrorBanner>{banner}</ErrorBanner> : null}
      <p className="text-sm">Xóa sự kiện “{session.name}”? Các khung sẽ trống lại.</p>
    </Modal>
  );
}
