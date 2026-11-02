"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";

/** Hộp xác nhận của trang (không dùng window.confirm). `onConfirm` trả lỗi (chuỗi) để hiện trong hộp, hoặc null khi xong. */
export function ConfirmDialog({
  title,
  body,
  cancelLabel = "Quay lại",
  confirmLabel,
  danger,
  onClose,
  onConfirm,
}: {
  title: string;
  body: React.ReactNode;
  cancelLabel?: string;
  confirmLabel: string;
  danger?: boolean;
  onClose: () => void;
  onConfirm: () => Promise<string | null>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const sending = useRef(false);

  async function go() {
    if (sending.current) return;
    sending.current = true;
    setBusy(true);
    setError("");
    const err = await onConfirm();
    sending.current = false;
    setBusy(false);
    if (err) setError(err);
  }

  return (
    <Modal
      sheet
      open
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button variant={danger ? "danger" : "primary"} onClick={() => void go()} loading={busy}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {error ? (
        <p role="alert" className="rounded-lg border border-danger/40 bg-danger-soft p-3 text-sm text-danger">
          {error}
        </p>
      ) : null}
      <div className="text-sm text-muted">{body}</div>
    </Modal>
  );
}
