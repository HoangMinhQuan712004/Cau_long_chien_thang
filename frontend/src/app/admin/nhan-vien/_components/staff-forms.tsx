import { useEffect, useState } from "react";
import { isPasswordValid } from "@/components/auth/password-rules";
import { Field } from "@/components/ui/field";
import { ResetIcon } from "@/components/ui/icons";
import { api } from "@/lib/api/client";
import type { Staff } from "@/lib/api/server";
import {
  type FormProps,
  NameInput,
  randomSuffix,
  PasswordField,
  StaffForm,
  usernamePreview,
  useStaffSubmit,
} from "./staff-form-kit";

// Form "Thêm nhân viên"; trả kèm mật khẩu vừa đặt
export function StaffCreateForm({ t, onCancel, onDone }: Omit<FormProps, "onDone"> & {
  onDone: (staff: Staff, password: string | null) => void;
}) {
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const { isPending, error, setError, submit } = useStaffSubmit(t);
  // Mã NV dự kiến (gọi một lần khi mở hộp), hiện dòng riêng; lỗi / chưa có ⇒ ẩn dòng
  const [nextCode, setNextCode] = useState<string | null>(null);
  useEffect(() => {
    let isCurrent = true;
    api
      .GET("/api/v1/admin/staff/next-code")
      .then(({ data }) => {
        if (isCurrent && data) setNextCode(data.staff_code);
      })
      .catch(() => undefined);
    return () => {
      isCurrent = false;
    };
  }, []);
  // Đuôi ngẫu nhiên sinh khi mở hộp (↻ để đổi); gửi kèm khi tạo nên tên thật trùng với xem trước
  const [suffix, setSuffix] = useState(randomSuffix);
  // 409 trùng tên đăng nhập ⇒ đã đổi đuôi, báo ngay dưới ô (không dùng Alert chung đầu form)
  const [isTaken, setIsTaken] = useState(false);
  const preview = usernamePreview(fullName, suffix);

  async function onSubmit() {
    const name = fullName.trim();
    if (!name) return setError(t.errors.fullName);
    if (!isPasswordValid(password)) return setError(t.errors.password);
    let created: Staff | undefined;
    let taken = false;
    setIsTaken(false);
    // `username_suffix`: trường tùy chọn mới của BE (gán qua biến để chạy được cả khi schema chưa có)
    const body = { full_name: name, password, username_suffix: suffix };
    const ok = await submit(async () => {
      const response = await api.POST("/api/v1/admin/staff", { body });
      created = response.data;
      taken = response.response.status === 409;
      return response;
    });
    // Trùng tên đăng nhập ⇒ tự đổi đuôi khác, báo bấm tạo lại
    if (taken) {
      setSuffix(randomSuffix());
      setIsTaken(true);
      return setError(null);
    }
    // Trả cả mật khẩu vừa đặt (tự gõ hay ngẫu nhiên) để khối "Đã tạo" hiện + chép gửi nhân viên
    if (ok && created) onDone(created, password);
  }

  return (
    <StaffForm
      {...{ t, isPending, error, onSubmit, onCancel }}
      submitLabel={t.create}
      canSubmit={isPasswordValid(password)}
    >
      {/* Đầu form: mã NV dự kiến (chỉ xem, không phải ô nhập) */}
      {nextCode ? (
        <p className="flex items-baseline gap-2 text-ui">
          <span className="text-muted">{t.nextCodeLabel}</span>
          <span className="text-sm font-semibold tabular-nums">{nextCode}</span>
        </p>
      ) : null}
      <Field label={t.fullNameLabel} htmlFor="staff-full-name">
        <NameInput id="staff-full-name" value={fullName} onChange={setFullName} disabled={isPending} />
        {/* Xem trước đầy đủ (to, rõ, xanh như Username) + ↻ đổi đuôi ngẫu nhiên khác */}
        {preview ? (
          <div className="flex flex-wrap items-center gap-x-1.5 text-ui text-muted">
            <span>{t.usernamePreview.split("{username}")[0].trim()}</span>
            <span aria-live="polite" className="font-mono text-sm font-semibold break-all text-primary">
              {preview}
            </span>
            <button
              type="button"
              onClick={() => {
                setSuffix(randomSuffix());
                setIsTaken(false);
              }}
              disabled={isPending}
              aria-label={t.regenerateSuffix}
              title={t.regenerateSuffix}
              className="relative grid size-7 place-items-center rounded-md hover:bg-primary-softer hover:text-primary focus-ring before:absolute before:-inset-1.5 [&>svg]:size-3.5"
            >
              <ResetIcon />
            </button>
            <span className="basis-full text-xs">{t.usernamePreviewHint}</span>
            {isTaken ? (
              <span role="alert" className="basis-full text-ui text-danger">
                {t.usernameTaken}
              </span>
            ) : null}
          </div>
        ) : null}
      </Field>
      <PasswordField
        t={t}
        id="staff-password"
        value={password}
        onChange={setPassword}
        disabled={isPending}
      />
    </StaffForm>
  );
}

// Sửa họ tên nhân viên
export function RenameForm({ t, staffId, initialName, onCancel, onDone }: FormProps & {
  staffId: number;
  initialName: string;
}) {
  const [fullName, setFullName] = useState(initialName);
  const { isPending, error, setError, submit } = useStaffSubmit(t);
  const inputId = `staff-${staffId}-name`;

  async function onSubmit() {
    const name = fullName.trim();
    if (!name) return setError(t.errors.fullName);
    const path = { staff_id: staffId };
    const ok = await submit(() =>
      api.PATCH("/api/v1/admin/staff/{staff_id}", { params: { path }, body: { full_name: name } }),
    );
    if (ok) onDone();
  }

  return (
    <StaffForm {...{ t, isPending, error, onSubmit, onCancel }} submitLabel={t.save}>
      <Field label={t.fullNameLabel} htmlFor={inputId}>
        <NameInput id={inputId} value={fullName} onChange={setFullName} disabled={isPending} />
      </Field>
    </StaffForm>
  );
}

// Admin đặt lại mật khẩu nhân viên
export function ResetPasswordForm({ t, staffId, onCancel, onDone }: Omit<FormProps, "onDone"> & {
  staffId: number;
  /** Đặt lại xong: trả mật khẩu mới để màn kết quả hiện + chép. */
  onDone: (password: string) => void;
}) {
  const [password, setPassword] = useState("");
  const { isPending, error, setError, submit } = useStaffSubmit(t);

  async function onSubmit() {
    if (!isPasswordValid(password)) return setError(t.errors.password);
    const path = { staff_id: staffId };
    const ok = await submit(() =>
      api.POST("/api/v1/admin/staff/{staff_id}/password", { params: { path }, body: { password } }),
    );
    if (ok) onDone(password);
  }

  return (
    <StaffForm
      {...{ t, isPending, error, onSubmit, onCancel }}
      submitLabel={t.save}
      canSubmit={isPasswordValid(password)}
    >
      <PasswordField
        t={t}
        id={`staff-${staffId}-password`}
        value={password}
        onChange={setPassword}
        disabled={isPending}
      />
    </StaffForm>
  );
}
