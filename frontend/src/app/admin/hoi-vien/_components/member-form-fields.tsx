import { Field, fieldErrorId } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { RadioGroup } from "@/components/ui/radio-group";
import { Dropdown } from "@/components/ui/dropdown";
import type { Dictionary } from "@/i18n/dictionaries";
import type { MemberFailure } from "@/lib/api/members";
import type { MemberRow } from "@/lib/api/server";
import { TIERS } from "./member-params";

export type MemberValues = {
  fullName: string;
  gender: "" | "male" | "female";
  phone: string;
  tier: string;
  racket: string;
  isActive: boolean;
};

export const EMPTY_MEMBER: MemberValues = { fullName: "", gender: "", phone: "", tier: "", racket: "", isActive: true };

// Hồ sơ (chi tiết hoặc dòng danh sách) ⇒ giá trị ban đầu của form; `phone`: số đầy đủ (Sửa) hoặc đã che (Chuyển)
export function valuesOf(d: MemberRow, phone: string): MemberValues {
  return {
    fullName: d.full_name,
    gender: d.gender ?? "",
    phone,
    tier: d.tier ?? "",
    // Giữ đúng chữ đang lưu (tự nhập, T-033)
    racket: d.racket ?? "",
    isActive: d.is_active,
  };
}

type Props = {
  id: string;
  values: MemberValues;
  onChange: (patch: Partial<MemberValues>) => void;
  /** Chỉ form hội viên (không phải hồ sơ tạm) có Hạng / Vợt. */
  withMemberFields: boolean;
  /** Form Sửa có Trạng thái Hoạt động / Ngừng. */
  withStatus: boolean;
  /** Nhân viên quầy: khóa Trạng thái. */
  isStatusLocked: boolean;
  /** Form Sửa: SĐT chỉ xem, không sửa. */
  isPhoneLocked?: boolean;
  error: MemberFailure | null;
  /** Hiện ngay dưới ô SĐT (khung đề nghị nâng hồ sơ tạm). */
  afterPhone?: React.ReactNode;
  /** Ghi chú cố định dưới ô SĐT (Thêm hội viên – T-026 AC1). */
  phoneNote?: string;
  t: Dictionary["members"];
};

/** Các ô của form hội viên / hồ sơ tạm (Figma P5a/b/f); lỗi E-001/002/018 hiện dưới đúng ô. */
export function MemberFormFields({ id, values, onChange, withMemberFields, withStatus, isStatusLocked, isPhoneLocked, error, afterPhone, phoneNote, t }: Props) {
  const f = t.form;
  const errorOf = (field: MemberFailure["field"]) => (error?.field === field ? error.message : undefined);
  const nameError = errorOf("full_name");
  const phoneError = errorOf("phone");

  return (
    <>
      {/* Từ sm hai cột bằng nhau: Họ tên / SĐT, Hạng / Vợt; Giới tính hàng riêng; điện thoại 1 cột */}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={f.nameLabel} htmlFor={`${id}-name`} error={nameError}>
          <Input
            compact
            id={`${id}-name`}
            value={values.fullName}
            onChange={(e) => onChange({ fullName: e.target.value })}
            placeholder={f.namePlaceholder}
            maxLength={100}
            autoComplete="off"
            required
            aria-invalid={nameError ? true : undefined}
            aria-describedby={nameError ? fieldErrorId(`${id}-name`) : undefined}
          />
        </Field>
        <Field
          label={f.phoneLabel}
          htmlFor={`${id}-phone`}
          error={phoneError}
        >
          <Input
            compact
            id={`${id}-phone`}
            type="tel"
            inputMode="tel"
            value={values.phone}
            onChange={(e) => onChange({ phone: e.target.value })}
            readOnly={isPhoneLocked}
            tabIndex={isPhoneLocked ? -1 : undefined}
            placeholder={f.phonePlaceholder}
            maxLength={20}
            autoComplete="off"
            required
            aria-invalid={phoneError ? true : undefined}
            aria-describedby={[phoneError ? fieldErrorId(`${id}-phone`) : null, phoneNote ? `${id}-phone-note` : null].filter(Boolean).join(" ") || undefined}
          />
          {phoneNote ? (
            <p id={`${id}-phone-note`} className="mt-1.5 text-xs text-muted">
              {phoneNote}
            </p>
          ) : null}
        </Field>
        <div className="sm:col-span-2">
        <RadioGroup
          name={`${id}-gender`}
          legend={f.genderLabel}
          value={values.gender}
          onChange={(gender) => onChange({ gender: gender as MemberValues["gender"] })}
          // "Không rõ" (giá trị rỗng) ⇒ gửi gender = null, bỏ chọn được
          options={[...(["male", "female"] as const).map((g) => ({ value: g, label: f.genders[g] })), { value: "", label: f.genderUnknown }]}
        />
        </div>
      </div>
      {afterPhone}
      {withMemberFields ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={f.tierLabel} htmlFor={`${id}-tier`}>
              <Dropdown
                id={`${id}-tier`}
                value={values.tier}
                onChange={(tier) => onChange({ tier })}
                // Lựa chọn đầu rỗng ⇒ gửi tier = null
                placeholder={t.tierNone}
                options={TIERS.map((x) => ({ value: x, label: x }))}
              />
            </Field>
            <Field label={f.racketLabel} htmlFor={`${id}-racket`}>
              <Input
                compact
                id={`${id}-racket`}
                value={values.racket}
                onChange={(e) => onChange({ racket: e.target.value })}
                placeholder={f.racketPlaceholder}
                maxLength={100}
                autoComplete="off"
              />
            </Field>
          </div>
        </>
      ) : null}
      {withStatus ? (
        <div className="flex flex-col gap-1.5">
          <RadioGroup
            name={`${id}-status`}
            legend={f.statusLabel}
            value={values.isActive ? "active" : "inactive"}
            onChange={(v) => onChange({ isActive: v === "active" })}
            options={(["active", "inactive"] as const).map((s) => ({ value: s, label: t.statuses[s] }))}
            disabled={isStatusLocked}
          />
          <p className="text-ui text-muted">{isStatusLocked ? f.lockedHint : f.inactiveHint}</p>
        </div>
      ) : null}
    </>
  );
}
