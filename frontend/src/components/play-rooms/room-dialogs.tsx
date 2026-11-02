"use client";

import { useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Modal } from "@/components/ui/modal";
import { formatTime } from "@/lib/format";
import { isValidPhone, normalizePhone } from "@/lib/phone";
import { ConfirmDialog } from "./confirm-dialog";
import { type CurrentMatch, FORMAT_LABEL } from "./types";

const names = (ps: { display_name: string }[]) => ps.map((p) => p.display_name).join(" · ");

/** "+ Mời người chơi": SĐT đầy đủ của hội viên có tài khoản (T-017 AC9). `onSend` trả câu lỗi để hiện dưới ô, hoặc null khi xong. */
export function InviteDialog({ onClose, onSend }: { onClose: () => void; onSend: (phone: string) => Promise<string | null> }) {
  const formId = useId();
  const inputId = useId();
  const sending = useRef(false);
  const [phone, setPhone] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (sending.current) return;
    const p = normalizePhone(phone);
    if (!phone.trim()) return setError("Vui lòng nhập Số điện thoại.");
    if (!isValidPhone(p)) return setError("Số điện thoại không hợp lệ.");
    sending.current = true;
    setBusy(true);
    setError("");
    const err = await onSend(p);
    sending.current = false;
    setBusy(false);
    if (err) setError(err);
  }

  return (
    <Modal
      sheet
      open
      onClose={onClose}
      title="Mời người chơi"
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Quay lại
          </Button>
          <Button type="submit" form={formId} loading={busy}>
            {busy ? "Đang gửi…" : "Gửi lời mời"}
          </Button>
        </>
      }
    >
      <form id={formId} onSubmit={submit} noValidate className="space-y-2">
        <label htmlFor={inputId} className="text-label font-semibold text-muted">
          Số điện thoại của người chơi
        </label>
        <Input
          id={inputId}
          value={phone}
          inputMode="tel"
          maxLength={13}
          placeholder="09xx xxx xxx"
          autoComplete="off"
          onChange={(e) => setPhone(e.target.value)}
          aria-invalid={Boolean(error) || undefined}
          aria-describedby={`${inputId}-hint`}
        />
        {error ? (
          <p role="alert" className="text-xs text-danger">
            {error}
          </p>
        ) : null}
        <p id={`${inputId}-hint`} className="text-xs text-subtle">
          Nhập đúng số điện thoại đầy đủ của hội viên đã có tài khoản. Người đó sẽ nhận lời mời trong thông báo.
        </p>
      </form>
    </Modal>
  );
}

/** "Nhập kết quả trận #n" → popup xác nhận → lưu (một lần, không sửa) – T-017 AC17. */
export function ResultDialog({
  match,
  onClose,
  onSave,
}: {
  match: CurrentMatch;
  onClose: () => void;
  /** Trả câu lỗi (hiện trong hộp xác nhận) hoặc null khi đã lưu. */
  onSave: (a: number, b: number) => Promise<string | null>;
}) {
  const idA = useId();
  const idB = useId();
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);

  const digits = (v: string) => v.replace(/\D/g, "").slice(0, 2);
  const valid = a !== "" && b !== "" && Number(a) !== Number(b);

  function next() {
    if (!valid) return setError("Tỉ số không hợp lệ (0–99, không hòa).");
    setError("");
    setConfirming(true);
  }

  const na = Number(a);
  const nb = Number(b);

  return (
    <>
      <Modal
        sheet
        open
        onClose={onClose}
        title={`Nhập kết quả trận #${match.no}`}
        footer={
          <>
            <Button variant="secondary" onClick={onClose}>
              Quay lại
            </Button>
            <Button onClick={next}>Lưu kết quả</Button>
          </>
        }
      >
        <p className="text-sm text-muted">
          {FORMAT_LABEL[match.format]}
          {match.started_at ? ` · bắt đầu ${formatTime(match.started_at)}` : ""}
        </p>
        <div className="grid grid-cols-[1fr_auto_1fr] items-end gap-3">
          <div className="min-w-0">
            <label htmlFor={idA} className="block text-xs font-semibold tracking-wide text-muted uppercase">
              Đội A
            </label>
            <p className="truncate text-sm font-medium">{names(match.team_a)}</p>
            <Input id={idA} value={a} inputMode="numeric" maxLength={2} onChange={(e) => setA(digits(e.target.value))} className="mt-2 text-center text-xl font-bold" aria-invalid={Boolean(error) || undefined} />
          </div>
          <span className="pb-2 text-xl font-bold text-muted" aria-hidden>
            :
          </span>
          <div className="min-w-0">
            <label htmlFor={idB} className="block text-xs font-semibold tracking-wide text-muted uppercase">
              Đội B
            </label>
            <p className="truncate text-sm font-medium">{names(match.team_b)}</p>
            <Input id={idB} value={b} inputMode="numeric" maxLength={2} onChange={(e) => setB(digits(e.target.value))} className="mt-2 text-center text-xl font-bold" aria-invalid={Boolean(error) || undefined} />
          </div>
        </div>
        {error ? (
          <p role="alert" className="text-xs text-danger">
            {error}
          </p>
        ) : null}
      </Modal>
      {confirming ? (
        <ConfirmDialog
          title={`Lưu kết quả Đội A ${na} – ${nb} Đội B?`}
          body="Đã lưu sẽ không sửa được."
          confirmLabel="Lưu kết quả"
          onClose={() => setConfirming(false)}
          onConfirm={async () => {
            const err = await onSave(na, nb);
            if (err) return err;
            setConfirming(false);
            return null;
          }}
        />
      ) : null}
    </>
  );
}
