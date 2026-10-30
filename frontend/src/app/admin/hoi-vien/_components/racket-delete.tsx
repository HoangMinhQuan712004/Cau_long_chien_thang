"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import type { Dictionary } from "@/i18n/dictionaries";
import { memberFailure } from "@/lib/api/members";
import type { Racket } from "@/lib/api/server";
import { toast } from "@/lib/feedback";
import type { useRackets } from "./use-rackets";

type Props = {
  racket: Racket;
  remove: ReturnType<typeof useRackets>["remove"];
  reload: () => void;
  onClose: () => void;
  t: Dictionary["members"];
};

/** Hộp xác nhận xóa vợt: báo số hội viên đang dùng (tên trong hồ sơ của họ vẫn giữ). */
export function RacketDelete({ racket, remove, reload, onClose, t }: Props) {
  const r = t.rackets;
  const [isPending, setIsPending] = useState(false);
  const name = racket.name;

  async function onConfirm() {
    setIsPending(true);
    const result = await remove(racket.id);
    setIsPending(false);
    if (result.ok) {
      toast(r.toast.deleted.replace("{name}", name));
    } else if (result.status === 404) {
      // Đã bị xóa ở nơi khác ⇒ tải lại cho khớp
      toast(r.deleteGone, undefined, "error");
      reload();
    } else {
      toast(memberFailure(result.error, result.response, t.errors).message, undefined, "error");
    }
    onClose();
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={r.deleteTitle}
      footer={
        <>
          <Button type="button" variant="secondary" onClick={onClose} disabled={isPending}>
            {t.form.cancel}
          </Button>
          <Button type="button" variant="danger" loading={isPending} onClick={() => void onConfirm()}>
            {isPending ? r.deleting : r.delete}
          </Button>
        </>
      }
    >
      <p className="text-sm">{r.confirmDelete.replace("{name}", name)}</p>
      {racket.member_count > 0 ? (
        <p className="text-sm text-muted">{r.confirmInUse.replace("{n}", String(racket.member_count))}</p>
      ) : null}
    </Modal>
  );
}
