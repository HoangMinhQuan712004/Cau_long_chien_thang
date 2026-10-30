"use client";

import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { InfoIcon } from "@/components/ui/icons";
import type { Dictionary } from "@/i18n/dictionaries";
import { api } from "@/lib/api/client";
import { type MemberFailure, type TempMatch, callMemberApi, memberFailure } from "@/lib/api/members";
import type { MemberRow, MemberTier } from "@/lib/api/server";
import { toast } from "@/lib/feedback";
import { formatPhone } from "@/lib/phone";
import type { FormMode } from "./member-form";
import { MemberFormFields, type MemberValues, RACKET_OTHER } from "./member-form-fields";
import { TempUpgradeNotice } from "./temp-upgrade-notice";
import { useRackets } from "./use-rackets";

type BodyProps = {
  canEditStatus: boolean;
  onClose: () => void;
  onSaved: () => void;
  t: Dictionary["members"];
  id: string;
  isPending: boolean;
  setIsPending: (value: boolean) => void;
  mode: FormMode;
  initial: MemberValues;
  profile: MemberRow | null;
};
/** Nội dung form (state, gọi API, lỗi); nút Lưu ở chân popup nối bằng form={id}. */
export function FormBody({ id, isPending, setIsPending, mode, initial, profile, canEditStatus, onClose, onSaved, t }: BodyProps) {
  const f = t.form;
  const [values, setValues] = useState(initial);
  const [error, setError] = useState<MemberFailure | null>(null);
  const [upgrade, setUpgrade] = useState<TempMatch | null>(null);
  const [nextCode, setNextCode] = useState<string | null>(null);
  // Form có Hạng / Vợt / Mã HV: Thêm hội viên và Sửa hội viên
  const isMemberForm = mode.kind === "add" || profile?.kind === "member";
  const rackets = useRackets(false, isMemberForm).state;

  // Mã HV sẽ cấp – chỉ để hiển thị trong ô khóa (mã thật lấy từ kết quả lưu)
  useEffect(() => {
    if (mode.kind !== "add") return;
    api.GET("/api/v1/members/next-code").then(({ data }) => data && setNextCode(data.member_code), () => {});
  }, [mode.kind]);

  const racket = values.racket === RACKET_OTHER ? values.racketOther.trim() || null : values.racket || null;
  const memberBody = {
    full_name: values.fullName,
    phone: values.phone,
    gender: values.gender || null,
    tier: (values.tier || null) as MemberTier | null,
    racket,
  };

  // Gửi theo loại form; Sửa chỉ gửi trường đã đổi (không bao giờ gửi SĐT)
  function request(upgradeTemp: boolean) {
    if (mode.kind === "temp") {
      const body = { full_name: values.fullName, phone: values.phone, gender: values.gender || null };
      return callMemberApi(() => api.POST("/api/v1/members/temp", { body }));
    }
    if (mode.kind === "add") {
      return callMemberApi(() => api.POST("/api/v1/members", { body: { ...memberBody, upgrade_temp: upgradeTemp } }));
    }
    const { fullName, gender, tier, isActive } = initial;
    const before: Record<string, unknown> = { full_name: fullName, gender: gender || null, tier: tier || null, racket: profile?.racket ?? null, is_active: isActive };
    // Hồ sơ tạm chỉ sửa tên + giới tính; Trạng thái chỉ Admin
    const editable = isMemberForm ? ["full_name", "gender", "tier", "racket", "is_active"] : ["full_name", "gender"];
    const isAllowed = (k: string) => editable.includes(k) && (canEditStatus || k !== "is_active");
    const changed = Object.fromEntries(
      Object.entries({ ...memberBody, is_active: values.isActive }).filter(([k, v]) => isAllowed(k) && before[k] !== v),
    );
    return callMemberApi(() => api.PATCH("/api/v1/members/{ref}", { params: { path: { ref: profile?.ref ?? "" } }, body: changed }));
  }

  async function save(upgradeTemp = false) {
    if (isPending) return;
    setIsPending(true);
    setError(null);
    const { data, error: apiError, response } = await request(upgradeTemp);
    setIsPending(false);
    if (data) return done(data as MemberRow);
    const failure = memberFailure(apiError, response, t.errors);
    if (failure.code === "E-MEM-3" || failure.code === "E-MEM-4") {
      toast(failure.message, undefined, "error");
      if (failure.code === "E-MEM-3") onSaved();
      return onClose();
    }
    // SĐT là hồ sơ tạm ⇒ không đóng form, đề nghị nâng; ô Họ tên trống thì điền tên hồ sơ tạm
    if (failure.temp) {
      const temp = failure.temp;
      setUpgrade(temp);
      setValues((v) => (v.fullName.trim() ? v : { ...v, fullName: temp.fullName }));
      return;
    }
    setUpgrade(null);
    setError(failure);
  }

  // Toast ✓ (P5g / Thêm / Sửa) rồi đóng popup, tải lại danh sách
  function done(row: MemberRow) {
    toastSaved(mode.kind, row, t.toast);
    onSaved();
    onClose();
  }

  return (
    <form
      id={id}
      noValidate
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
      className="flex flex-col gap-4"
    >
      {error && !error.field ? <Alert variant="error">{error.message}</Alert> : null}
      {isMemberForm ? (
        // Mã tự cấp khi lưu ⇒ chỉ hiện chữ, không phải ô nhập
        <p className="text-sm text-muted">
          {f.codeLabel}:{" "}
          <span className="font-bold text-primary tabular-nums">{profile?.member_code ?? nextCode ?? "…"}</span>
          {mode.kind === "edit" ? null : <span className="ml-2 text-xs">({f.codeHint})</span>}
        </p>
      ) : null}
      <MemberFormFields
        id={id}
        values={values}
        onChange={(patch) => {
          // Đổi SĐT ⇒ bỏ đề nghị nâng hồ sơ tạm của số cũ
          if ("phone" in patch) setUpgrade(null);
          setValues((v) => ({ ...v, ...patch }));
        }}
        withMemberFields={isMemberForm}
        withStatus={mode.kind === "edit" && isMemberForm}
        isStatusLocked={!canEditStatus}
        isPhoneLocked={mode.kind === "edit"}
        racketNames={rackets.status === "ok" ? rackets.items.map((r) => r.name) : []}
        error={error}
        afterPhone={
          upgrade ? (
            <TempUpgradeNotice temp={upgrade} isPending={isPending} onUpgrade={() => void save(true)} onDismiss={() => setUpgrade(null)} t={f} />
          ) : null
        }
        t={t}
      />
      {mode.kind === "temp" ? <TempNote text={t.temp.note} /> : null}
    </form>
  );
}

/** Ghi chú dưới form Tạo hồ sơ tạm: một dòng chữ phụ, không khung. */
function TempNote({ text }: { text: string }) {
  return (
    <p className="flex items-start gap-1.5 text-ui text-muted">
      <InfoIcon size={16} className="mt-px shrink-0" />
      {text}
    </p>
  );
}

/** Toast sau khi lưu: tạo hồ sơ tạm / sửa / thêm hội viên (chưa xếp hạng ⇒ bỏ phần "· Hạng …"). */
function toastSaved(kind: "add" | "temp" | "edit", row: MemberRow, t: Dictionary["members"]["toast"]) {
  const memberSub = (row.tier ? t.memberSub : t.memberSubNoTier)
    .replace("{name}", row.full_name)
    .replace("{code}", row.member_code ?? "")
    .replace("{tier}", row.tier ?? "");
  const tempSub = t.tempSub.replace("{name}", row.full_name).replace("{phone}", formatPhone(row.phone));
  if (kind === "temp") toast(t.tempCreated, tempSub);
  else if (kind === "edit") toast(t.saved, row.kind === "member" ? memberSub : tempSub);
  else toast(t.added, memberSub);
}
