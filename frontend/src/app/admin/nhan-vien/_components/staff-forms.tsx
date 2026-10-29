import { useState } from "react";
import { isPasswordValid } from "@/components/auth/password-rules";
import { Field } from "@/components/ui/field";
import { api } from "@/lib/api/client";
import type { Staff } from "@/lib/api/server";
import {
  type FormProps,
  NameInput,
  PasswordField,
  StaffForm,
  useStaffSubmit,
} from "./staff-form-kit";

// Form "Thêm nhân viên"; trả kèm mật khẩu nếu do nút ngẫu nhiên sinh
export function StaffCreateForm({ t, onCancel, onDone }: Omit<FormProps, "onDone"> & {
  onDone: (staff: Staff, generatedPassword: string | null) => void;
}) {
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [isGenerated, setIsGenerated] = useState(false);
  const { isPending, error, setError, submit } = useStaffSubmit(t);

  async function onSubmit() {
    const name = fullName.trim();
    if (!name) return setError(t.errors.fullName);
    if (!isPasswordValid(password)) return setError(t.errors.password);
    let created: Staff | undefined;
    const ok = await submit(async () => {
      const response = await api.POST("/api/v1/admin/staff", { body: { full_name: name, password } });
      created = response.data;
      return response;
    });
    if (ok && created) onDone(created, isGenerated ? password : null);
  }

  return (
    <StaffForm
      {...{ t, isPending, error, onSubmit, onCancel }}
      submitLabel={t.create}
      canSubmit={isPasswordValid(password)}
    >
      <h2 className="text-lg font-bold">{t.add}</h2>
      <Field label={t.fullNameLabel} htmlFor="staff-full-name">
        <NameInput id="staff-full-name" value={fullName} onChange={setFullName} disabled={isPending} />
      </Field>
      <PasswordField
        t={t}
        id="staff-password"
        value={password}
        onChange={(value, generated) => {
          setPassword(value);
          setIsGenerated(!!generated);
        }}
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
export function ResetPasswordForm({ t, staffId, onCancel, onDone }: FormProps & { staffId: number }) {
  const [password, setPassword] = useState("");
  const { isPending, error, setError, submit } = useStaffSubmit(t);

  async function onSubmit() {
    if (!isPasswordValid(password)) return setError(t.errors.password);
    const path = { staff_id: staffId };
    const ok = await submit(() =>
      api.POST("/api/v1/admin/staff/{staff_id}/password", { params: { path }, body: { password } }),
    );
    if (ok) onDone();
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
