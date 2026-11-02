"use client";

import { useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import type { Dictionary } from "@/i18n/dictionaries";
import { toast } from "@/lib/feedback";
import { formatDateTime } from "@/lib/format";
import { formatPhone } from "@/lib/phone";
import type { AccountCreated } from "./member-form";

type Props = { info: AccountCreated; t: Dictionary["members"]; onClose: () => void };

/** Hộp "Đã tạo tài khoản…" sau khi Thêm hội viên mà SĐT chưa có tài khoản (T-026 AC2): không tự tắt, có Sao chép + Đóng. */
export function AccountNotice({ info, t, onClose }: Props) {
  const n = t.accountNotice;
  const [failed, setFailed] = useState(false);
  const phone = info.phone;
  const lines = [
    n.created.replace("{code}", info.row.member_code ?? "").replace("{name}", info.row.full_name),
    n.login.replaceAll("{phone}", phone),
    ...(info.expiresAt ? [n.expires.replace("{at}", formatDateTime(info.expiresAt))] : []),
  ];

  async function copy() {
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setFailed(false);
      toast(n.copied, undefined, "success");
    } catch {
      setFailed(true);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={n.title}
      footer={
        <div className="flex w-full flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="secondary" onClick={onClose}>
            {n.close}
          </Button>
          <Button type="button" onClick={() => void copy()}>
            {n.copy}
          </Button>
        </div>
      }
    >
      <div role="status" className="
        space-y-2 rounded-xl border border-primary/40 bg-primary-softer p-4 text-sm
      ">
        <p className="font-semibold">{lines[0]}</p>
        <p>
          {n.login.split("{phone}")[0]}
          <b className="tabular-nums">{formatPhone(phone)}</b>
          {n.login.split("{phone}")[1]}
          <b className="tabular-nums">{formatPhone(phone)}</b>
        </p>
        {lines[2] ? <p className="text-muted">{lines[2]}</p> : null}
      </div>
      {failed ? <Alert variant="error">{n.copyFailed}</Alert> : null}
    </Modal>
  );
}
