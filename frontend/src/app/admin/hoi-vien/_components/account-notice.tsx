"use client";

import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { CheckIcon, ClockIcon, CopyIcon } from "@/components/ui/icons";
import { Modal } from "@/components/ui/modal";
import type { Dictionary } from "@/i18n/dictionaries";
import { formatDateTime } from "@/lib/format";
import { formatPhone } from "@/lib/phone";
import type { AccountCreated } from "./member-form";

type Props = { info: AccountCreated; t: Dictionary["members"]; onClose: () => void };

/** Hộp "Đã tạo tài khoản" sau khi Thêm hội viên mà SĐT chưa có tài khoản (T-026 AC2): không tự tắt, đóng bằng (x). */
export function AccountNotice({ info, t, onClose }: Props) {
  const n = t.accountNotice;
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState(false);
  const phone = info.phone;
  // Mật khẩu ban đầu = SĐT (T-026); hiện nhóm 4-3-3 cho dễ đọc, sao chép số liền để dán đăng nhập được ngay
  const rows = [
    [n.phoneLabel, phone],
    [n.passwordLabel, phone],
  ] as const;

  // Nút về lại "Sao chép" sau 2 giây
  useEffect(() => {
    if (!copied) return;
    const id = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(id);
  }, [copied]);

  async function copy() {
    try {
      await navigator.clipboard.writeText(n.copyText.replaceAll("{phone}", phone));
      setFailed(false);
      setCopied(true);
    } catch {
      setFailed(true);
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={n.title}
      subtitle={n.subtitle.replace("{code}", info.row.member_code ?? "").replace("{name}", info.row.full_name)}
      footer={
        <div className="flex w-full sm:justify-end">
          <Button type="button" className="w-full sm:w-auto" onClick={() => void copy()} aria-live="polite">
            {copied ? <CheckIcon size={16} /> : <CopyIcon size={16} />}
            {copied ? n.copied : n.copy}
          </Button>
        </div>
      }
    >
      <div role="status" className="flex flex-col gap-4">
        <dl className="divide-y rounded-xl bg-primary-softer px-4">
          {rows.map(([label, value]) => (
            <div key={label} className="flex items-center justify-between gap-4 py-3">
              <dt className="text-sm text-muted">{label}</dt>
              <dd className="text-base font-semibold whitespace-nowrap tabular-nums">{formatPhone(value)}</dd>
            </div>
          ))}
        </dl>
        {info.expiresAt ? (
          <p className="flex gap-2 text-ui text-muted">
            <ClockIcon size={16} className="mt-0.5 shrink-0" />
            <span>{n.expires.replace("{at}", formatDateTime(info.expiresAt))}</span>
          </p>
        ) : null}
      </div>
      {failed ? <Alert variant="error">{n.copyFailed}</Alert> : null}
    </Modal>
  );
}
