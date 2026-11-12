"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Modal } from "@/components/ui/modal";
import { errorText, write } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatDateTime, formatLongDate, formatVnd, hhmm } from "@/lib/format";
import { formatPhone, normalizePhone } from "@/lib/phone";
import { authFailure, STALE_CODES } from "./booking-dialogs";
import { CustomerPicker, customerErrors, customerPayload, emptyCustomer, type CustomerState } from "./customer-picker";
import { getSession, sendDeleteSession, sendTicketBatch } from "./requests";
import type { CustomerPayload, Item, SessionDetail } from "./types";
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
  /** Mở vé; `collect` = mở thẳng bước Thu tiền (T-068). */
  onOpenTicket: (code: string, collect?: boolean) => void;
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
        onRefresh={async () => {
          onChanged();
          await load();
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
                  <th className="px-3 py-1.5">
                    <span className="sr-only">Thao tác</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {s.tickets.map((t) => (
                  // T-068: cả dòng bấm được (mở thông tin vé); nút trong dòng tự chặn để không mở hai lần
                  <tr key={t.code} onClick={() => onOpenTicket(t.code)} className="cursor-pointer border-b border-border last:border-0 hover:bg-primary-softer">
                    <td className="px-3 py-2 font-mono text-xs">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onOpenTicket(t.code);
                        }}
                        className="text-primary hover:underline focus-ring"
                      >
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
                    <td className="px-3 py-1.5 text-right">
                      {t.payment_status === "unpaid" && t.source !== "online" ? (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onOpenTicket(t.code, true);
                          }}
                          className="relative inline-flex min-h-8 items-center rounded-md bg-primary px-3 text-xs font-semibold whitespace-nowrap text-white hover:bg-primary-hover focus-ring before:absolute before:-inset-1"
                          aria-label={`Thu tiền vé ${t.code}`}
                        >
                          Thu tiền
                        </button>
                      ) : null}
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

/** Một người trong danh sách đăng ký (T-071): hội viên (mã HV) hoặc hồ sơ tạm (SĐT). */
type Person = { key: string; name: string; phone: string; memberCode: string | null; payload: CustomerPayload };

function personOf(c: CustomerState): Person | null {
  const payload = customerPayload(c);
  if (!payload || Object.keys(customerErrors(c)).length) return null;
  if ("member_code" in payload) {
    const m = c.picked;
    if (!m) return null;
    return { key: `m:${m.member_code}`, name: m.name, phone: normalizePhone(m.phone), memberCode: m.member_code, payload };
  }
  return { key: `t:${payload.temp.phone}`, name: payload.temp.full_name, phone: payload.temp.phone, memberCode: null, payload };
}

/**
 * Đăng ký vé cho nhiều người một lần (T-071): thêm hội viên (chọn là vào danh sách) hoặc hồ sơ tạm (nút Thêm), tối đa số chỗ
 * còn, không trùng người. Gửi một lệnh batch (tất cả hoặc không): thiếu chỗ ⇒ báo "Chỉ còn n chỗ", danh sách giữ nguyên để sửa.
 */
function TicketDialog({
  session,
  onBack,
  onClose,
  onRegistered,
  onRefresh,
  onStale,
}: {
  session: SessionDetail;
  onBack: () => void;
  onClose: () => void;
  onRegistered: () => Promise<void>;
  /** Tải lại sự kiện mà vẫn ở hộp đăng ký (số chỗ còn mới), danh sách đã chọn giữ nguyên. */
  onRefresh: () => Promise<void>;
  onStale: (message: string) => Promise<void>;
}) {
  const [customer, setCustomer] = useState<CustomerState>(emptyCustomer);
  const [pickerKey, setPickerKey] = useState(0);
  const [people, setPeople] = useState<Person[]>([]);
  const [addTried, setAddTried] = useState(false);
  const [banner, setBanner] = useState("");
  const [busy, setBusy] = useState(false);
  const s = session;
  const remaining = Math.max(0, s.capacity - s.taken);
  const full = people.length >= remaining;
  // Hội viên đã có vé trong sự kiện (so theo mã HV) ⇒ nhãn "Đã có vé", vẫn đăng ký được. Hồ sơ tạm không có mã nên không có nhãn.
  const ticketed = new Set(s.tickets.flatMap((t) => (t.customer_kind === "member" && t.member_code ? [t.member_code] : [])));

  // Danh sách mới nhất, đọc đồng bộ (kiểm trùng / đủ chỗ không phụ thuộc lần render). Một cú bấm chỉ phát MỘT lần chọn:
  // ô radio trong hàng hội viên chặn sự kiện nổi lên hàng (customer-picker.tsx)
  const peopleRef = useRef<Person[]>([]);

  function add(c: CustomerState): boolean {
    const p = personOf(c);
    if (!p) {
      setAddTried(true); // hồ sơ tạm thiếu tên / SĐT: hiện lỗi dưới ô
      return false;
    }
    const current = peopleRef.current;
    if (current.some((x) => x.key === p.key)) {
      setBanner(`${p.name} đã có trong danh sách.`);
      return false;
    }
    if (current.length >= remaining) {
      setBanner(`Chỉ còn ${remaining} chỗ.`);
      return false;
    }
    setBanner("");
    peopleRef.current = [...current, p];
    setPeople(peopleRef.current);
    setCustomer({ ...emptyCustomer, mode: c.mode });
    setPickerKey((k) => k + 1); // dựng lại ô tìm cho người tiếp theo
    setAddTried(false);
    return true;
  }

  // Hội viên: chọn trong danh sách tìm là thêm luôn; hồ sơ tạm: điền rồi bấm "Thêm vào danh sách"
  function onPick(next: CustomerState) {
    if (next.mode === "member" && next.picked && next.picked !== customer.picked) {
      if (!add(next)) setCustomer({ ...next, picked: null });
      return;
    }
    setCustomer(next);
  }

  async function submit() {
    setBanner("");
    if (!people.length) return;
    setBusy(true);
    try {
      const res = await write((key) =>
        sendTicketBatch(
          key,
          s.code,
          people.map((p) => p.payload),
        ),
      );
      if (!res.ok) {
        const e = res.error;
        if (authFailure(e)) return;
        if (e.code === "E-024") {
          // Máy khác vừa bán mất chỗ (AC3): không vé nào được tạo; báo "Chỉ còn n chỗ.", cập nhật số chỗ, giữ danh sách để bớt người
          setBanner(errorText(e));
          await onRefresh();
          return;
        }
        if (e.code && STALE_CODES.includes(e.code)) return void (await onStale(errorText(e)));
        setBanner(errorText(e)); // E-001 / E-004…: giữ danh sách để sửa
        return;
      }
      const out = res.data as { tickets: Item[] };
      toast(`Đã đăng ký ${out.tickets.length} vé`, "Trạng thái: Chưa thanh toán · thu tiền tại quầy");
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
          <button type="button" onClick={submit} disabled={busy || !people.length || people.length > remaining} className={btnPrimaryCls}>
            {busy ? "Đang đăng ký…" : people.length > 1 ? `Đăng ký ${people.length} vé` : "Đăng ký vé"}
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
          Còn {remaining} chỗ (đã đăng ký {s.taken}/{s.capacity})
        </p>
      </SummaryBox>
      <section aria-label="Người đăng ký" className="space-y-2">
        <div className="flex items-baseline justify-between gap-2 text-sm">
          <span className="font-semibold">Người đăng ký ({people.length})</span>
          <span className={full ? "font-medium text-danger" : "text-muted"}>Còn {Math.max(0, remaining - people.length)} chỗ</span>
        </div>
        {people.length ? (
          <ul className="divide-y divide-border rounded-md border border-border">
            {people.map((p) => (
              <li key={p.key} className="flex items-center gap-2 px-3 py-2 text-sm">
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">
                    {p.name}
                    <span className="ml-1.5 text-xs font-normal text-muted">{"member_code" in p.payload ? p.payload.member_code : "Hồ sơ tạm"}</span>
                  </span>
                  <span className="block text-xs text-muted tabular-nums">{formatPhone(p.phone)}</span>
                </span>
                {p.memberCode && ticketed.has(p.memberCode) ? <span className="shrink-0 rounded-full bg-primary-softer px-2 py-0.5 text-xs font-medium text-primary">Đã có vé</span> : null}
                <button
                  type="button"
                  onClick={() => {
                    peopleRef.current = peopleRef.current.filter((x) => x.key !== p.key);
                    setPeople(peopleRef.current);
                  }}
                  disabled={busy}
                  aria-label={`Bỏ ${p.name} khỏi danh sách`}
                  className="relative grid size-8 shrink-0 place-items-center rounded-full text-muted hover:bg-danger-soft hover:text-danger focus-ring before:absolute before:-inset-1"
                >
                  <span aria-hidden>✕</span>
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="rounded-md border border-dashed border-border px-3 py-3 text-center text-xs text-muted">Chưa có ai. Tìm hội viên hoặc nhập hồ sơ tạm bên dưới.</p>
        )}
      </section>

      {people.length > remaining ? (
        <p role="alert" className="text-sm font-medium text-danger">
          Danh sách nhiều hơn số chỗ còn ({remaining}). Bỏ bớt {people.length - remaining} người rồi đăng ký.
        </p>
      ) : null}
      {full ? (
        <p className="text-sm text-muted">Đã đủ số chỗ còn trống. Bỏ bớt người để thêm người khác.</p>
      ) : (
        <div className="space-y-2">
          <CustomerPicker key={pickerKey} state={customer} onChange={onPick} submitted={addTried} />
          {customer.mode === "temp" ? (
            <button type="button" onClick={() => add(customer)} disabled={busy} className={btnCls}>
              Thêm vào danh sách
            </button>
          ) : null}
        </div>
      )}
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
