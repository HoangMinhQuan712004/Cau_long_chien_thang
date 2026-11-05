"use client";

import { useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/ui/modal";
import { api } from "@/lib/api/client";
import type { Staff } from "@/lib/api/server";
import { toast } from "@/lib/feedback";
import { type StaffTexts, useStaffSubmit } from "./staff-form-kit";
import { RenameForm, ResetPasswordForm, StaffCreateForm } from "./staff-forms";
import { CopyButton, copyText, Username } from "./staff-table";

// Các hộp thoại của màn Nhân viên: Thêm / Sửa tên / Đặt lại mật khẩu (bọc form sẵn có) + xác nhận Khóa.
// Điện thoại: bảng trượt từ đáy (Modal `sheet`); nút ở cuối rộng bằng nhau.

export type StaffDialog =
  | { kind: "create" }
  | { kind: "rename"; staff: Staff }
  | { kind: "password"; staff: Staff }
  | { kind: "lock"; staff: Staff };

type Props = {
  dialog: StaffDialog;
  onClose: () => void;
  /** Ghi xong: cha tải lại danh sách. */
  onChanged: () => void;
  /** Đóng màn kết quả sau khi tạo: cha tải lại bảng và tô nổi dòng mới (?ma=). */
  onCreated: (staff: Staff) => void;
  t: StaffTexts;
};

export function StaffDialogs({ dialog, onClose, onChanged, onCreated, t }: Props) {
  const done = () => {
    onClose();
    onChanged();
  };

  if (dialog.kind === "create") return <CreateDialog onClose={onClose} onCreated={onCreated} t={t} />;
  if (dialog.kind === "rename") {
    return (
      <Modal open sheet onClose={onClose} title={t.editName} subtitle={`${dialog.staff.staff_code} · ${dialog.staff.username}`}>
        <RenameForm t={t} staffId={dialog.staff.id} initialName={dialog.staff.full_name} onCancel={onClose} onDone={done} />
      </Modal>
    );
  }
  if (dialog.kind === "password") return <ResetDialog staff={dialog.staff} onClose={onClose} onDone={done} t={t} />;
  return <LockDialog staff={dialog.staff} onClose={onClose} onDone={done} t={t} />;
}

/** Một dòng của màn kết quả: nhãn + giá trị; "username" = Username xanh (có chép), "secret" / "plain" = mono + nút chép. */
type CredentialRow = { label: string; value: string; kind: "username" | "secret" | "plain" };

/**
 * Màn kết quả dùng chung (Đã tạo nhân viên / Đã đặt lại mật khẩu): các dòng có nút chép + [Đóng] [Chép tất cả]
 * ("Tên đăng nhập: … / Mật khẩu: …"). Mật khẩu chỉ hiện một lần (chỉ giữ trong bộ nhớ popup).
 */
function CredentialsResult({ title, hint, heading, rows, username, password, onClose, t }: {
  title: string;
  hint: string;
  /** Dòng đậm trên cùng (vd tên nhân viên vừa tạo). */
  heading?: string;
  rows: CredentialRow[];
  username: string;
  password: string;
  onClose: () => void;
  t: StaffTexts;
}) {
  const all = password ? t.copyAllText.replace("{username}", username).replace("{password}", password) : username;

  return (
    <Modal
      open
      sheet
      onClose={onClose}
      title={title}
      subtitle={hint}
      footer={
        <div className="grid w-full grid-cols-2 gap-2">
          <Button type="button" variant="secondary" block onClick={onClose}>
            {t.close}
          </Button>
          <Button type="button" block onClick={() => void copyText(all, t)}>
            {t.copyAll}
          </Button>
        </div>
      }
    >
      {heading ? <p className="font-semibold">{heading}</p> : null}
      <dl className="grid grid-cols-[7.5rem_minmax(0,1fr)] items-center gap-x-3 gap-y-2">
        {rows.map((r) => (
          <div key={r.label} className="contents">
            <dt className="text-ui text-muted">{r.label}</dt>
            <dd className="min-w-0">
              {r.kind === "username" ? (
                <Username value={r.value} t={t} />
              ) : (
                <span className="inline-flex max-w-full items-center gap-0.5">
                  <span className={r.kind === "secret" ? "font-mono text-sm font-semibold break-all" : "text-sm font-semibold"}>{r.value}</span>
                  <CopyButton value={r.value} label={r.label} t={t} />
                </span>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </Modal>
  );
}

/** Thêm nhân viên: tạo xong thì CHUYỂN NỘI DUNG popup sang màn kết quả (không chèn khối lên trang). */
function CreateDialog({ onClose, onCreated, t }: { onClose: () => void; onCreated: (staff: Staff) => void; t: StaffTexts }) {
  const [result, setResult] = useState<{ staff: Staff; password: string } | null>(null);
  if (!result) {
    return (
      <Modal open sheet onClose={onClose} title={t.add}>
        <StaffCreateForm t={t} onCancel={onClose} onDone={(staff, password) => setResult({ staff, password: password ?? "" })} />
      </Modal>
    );
  }
  const { staff, password } = result;
  return (
    <CredentialsResult
      title={t.createdTitle}
      hint={t.createdHint}
      heading={staff.full_name}
      rows={[
        { label: t.codeLabel, value: staff.staff_code, kind: "secret" },
        { label: t.usernameLabel, value: staff.username, kind: "username" },
        ...(password ? [{ label: t.passwordLabel, value: password, kind: "secret" as const }] : []),
      ]}
      username={staff.username}
      password={password}
      onClose={() => onCreated(staff)}
      t={t}
    />
  );
}

/** Đặt lại mật khẩu: xong thì chuyển sang màn kết quả (như Đã tạo); đóng ⇒ cha tải lại (số thiết bị về 0). */
function ResetDialog({ staff, onClose, onDone, t }: { staff: Staff; onClose: () => void; onDone: () => void; t: StaffTexts }) {
  const [password, setPassword] = useState<string | null>(null);
  if (password === null) {
    return (
      <Modal open sheet onClose={onClose} title={t.resetPassword} subtitle={`${staff.full_name} · ${staff.staff_code}`}>
        <ResetPasswordForm t={t} staffId={staff.id} onCancel={onClose} onDone={setPassword} />
      </Modal>
    );
  }
  return (
    <CredentialsResult
      title={t.resetDoneTitle}
      hint={t.resetDoneHint}
      rows={[
        { label: t.colName, value: staff.full_name, kind: "plain" },
        { label: t.usernameLabel, value: staff.username, kind: "username" },
        { label: t.newPasswordLabel, value: password, kind: "secret" },
      ]}
      username={staff.username}
      password={password}
      onClose={onDone}
      t={t}
    />
  );
}

/** Xác nhận Khóa (thay cho "bấm lần nữa để khóa" trên nút): Hủy | Khóa (đỏ), rộng bằng nhau. */
function LockDialog({ staff, onClose, onDone, t }: { staff: Staff; onClose: () => void; onDone: () => void; t: StaffTexts }) {
  const { isPending, error, submit } = useStaffSubmit(t);

  async function lock() {
    const ok = await submit(() =>
      api.PATCH("/api/v1/admin/staff/{staff_id}", { params: { path: { staff_id: staff.id } }, body: { is_active: false } }),
    );
    if (!ok) return;
    toast(t.locked.replace("{name}", staff.full_name));
    onDone();
  }

  return (
    <Modal
      open
      sheet
      onClose={onClose}
      title={t.lockTitle.replace("{name}", staff.full_name)}
      footer={
        <div className="grid w-full grid-cols-2 gap-2">
          <Button type="button" variant="secondary" block onClick={onClose} disabled={isPending}>
            {t.cancel}
          </Button>
          <Button type="button" variant="danger" block loading={isPending} onClick={() => void lock()}>
            {t.lock}
          </Button>
        </div>
      }
    >
      {error && <Alert variant="error">{error}</Alert>}
      <p className="text-sm text-muted">{t.lockBody}</p>
    </Modal>
  );
}

/** Mở khóa: không cần hỏi lại (đảo được ngay), báo bằng toast. */
export function useUnlock(t: StaffTexts, onChanged: () => void) {
  const { isPending, submit } = useStaffSubmit(t);
  return async (staff: Staff) => {
    if (isPending) return;
    const ok = await submit(() =>
      api.PATCH("/api/v1/admin/staff/{staff_id}", { params: { path: { staff_id: staff.id } }, body: { is_active: true } }),
    );
    toast(ok ? t.unlocked.replace("{name}", staff.full_name) : t.errors.generic, undefined, ok ? "success" : "error");
    if (ok) onChanged();
  };
}
