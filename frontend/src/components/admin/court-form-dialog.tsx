"use client";

import { useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import type { Dictionary } from "@/i18n/dictionaries";
import { api } from "@/lib/api/client";
import { write } from "@/lib/api/write";
import { ConflictList, CourtForm } from "./court-form";
import { bannerFrom, withoutConflict, type Banner, type Form, type Resource, type ResourceType } from "./court-form-logic";
import { useCourtForm } from "./use-court-form";

const FOOTER = "grid w-full grid-cols-2 gap-2";

/** Popup "Thêm sân" (sửa sân nằm trong ngăn chi tiết): điện thoại trượt từ đáy, 2 nút chân rộng bằng nhau. */
export function CourtFormDialog({
  initial,
  resources,
  types,
  t,
  onClose,
  onSaved,
  onReload,
}: {
  initial: Form;
  resources: Resource[];
  types: ResourceType[];
  t: Dictionary["courts"];
  onClose: () => void;
  onSaved: (code: string) => void;
  onReload: () => void;
}) {
  const state = useCourtForm(initial, resources, onSaved);
  return (
    <Modal
      open
      sheet
      onClose={onClose}
      size="medium"
      title={t.add}
      footer={
        <div className={FOOTER}>
          <Button type="button" variant="secondary" block onClick={onClose} disabled={state.busy}>
            {t.cancel}
          </Button>
          <Button type="button" block onClick={() => void state.submit()} loading={state.busy}>
            {state.busy ? t.saving : t.add}
          </Button>
        </div>
      }
    >
      <CourtForm state={state} types={types} onReload={onReload} t={t} />
    </Modal>
  );
}

/** Xác nhận xóa sân: Hủy | Xóa (đỏ), rộng bằng nhau; 409 (còn lịch sắp tới) hiện câu của backend + các mã bấm mở được. */
export function DeleteCourtDialog({ court, onClose, onDeleted, t }: { court: Resource; onClose: () => void; onDeleted: () => void; t: Dictionary["courts"] }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Banner | null>(null);

  async function confirm() {
    if (busy) return;
    setBusy(true);
    setError(null);
    const res = await write((key) =>
      api.DELETE("/api/v1/booking/resources/{code}", { params: { path: { code: court.code } }, headers: { "Idempotency-Key": key } }),
    );
    setBusy(false);
    // 404: đã bị xóa ở nơi khác ⇒ coi như xong
    if (res.ok || res.error.status === 404) onDeleted();
    else setError(bannerFrom(res.error));
  }

  return (
    <Modal
      open
      sheet
      onClose={onClose}
      title={t.deleteTitle.replace("{name}", court.name)}
      footer={
        <div className={FOOTER}>
          <Button type="button" variant="secondary" block onClick={onClose} disabled={busy}>
            {t.cancel}
          </Button>
          <Button type="button" variant="danger" block loading={busy} onClick={() => void confirm()}>
            {busy ? t.deleting : t.delete}
          </Button>
        </div>
      }
    >
      {error ? (
        <Alert variant={error.done ? "info" : "error"}>
          <span className="flex flex-col gap-1.5">
            <span>{error.text}</span>
            {error.items?.length ? (
              <ConflictList
                items={error.items}
                more={error.more}
                court={court.code}
                onResolved={(code) => setError((b) => b && withoutConflict(b, code, t.form.conflictsDone.delete))}
                t={t.form}
              />
            ) : null}
          </span>
        </Alert>
      ) : null}
      <p className="text-sm text-muted">{t.deleteBody}</p>
    </Modal>
  );
}
