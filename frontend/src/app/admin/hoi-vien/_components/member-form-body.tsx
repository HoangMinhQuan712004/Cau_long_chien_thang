"use client";

import { useEffect, useRef, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { InfoIcon } from "@/components/ui/icons";
import type { Dictionary } from "@/i18n/dictionaries";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { type MemberFailure, callMemberApi, memberFailure } from "@/lib/api/members";
import { newIdempotencyKey } from "@/lib/api/write";
import type { MemberCreated, MemberRow, MemberTier } from "@/lib/api/server";
import { toast } from "@/lib/feedback";
import { formatPhone } from "@/lib/phone";
import type { AccountCreated, FormMode } from "./member-form";
import { MemberFormFields, type MemberValues, RACKET_OTHER } from "./member-form-fields";
import { useRackets } from "./use-rackets";

type BodyProps = {
  canEditStatus: boolean;
  onClose: () => void;
  onSaved: () => void;
  /** Thêm hội viên mà SĐT chưa có tài khoản (T-026 AC2): cha hiện hộp thông báo thay cho form. */
  onAccountCreated: (info: AccountCreated) => void;
  /** Hồ sơ đã đổi ở máy khác (409 E-MEM-9): tải lại bản mới nhất. */
  onReload: () => void;
  t: Dictionary["members"];
  id: string;
  isPending: boolean;
  setIsPending: (value: boolean) => void;
  mode: FormMode;
  initial: MemberValues;
  profile: MemberRow | null;
};
/** Nội dung form (state, gọi API, lỗi); nút Lưu ở chân popup nối bằng form={id}. */
export function FormBody({ id, isPending, setIsPending, mode, initial, profile, canEditStatus, onClose, onSaved, onAccountCreated, onReload, t }: BodyProps) {
  const f = t.form;
  const [values, setValues] = useState(initial);
  const [error, setError] = useState<MemberFailure | null>(null);
  const [isStale, setIsStale] = useState(false);
  // Thêm / Tạo hồ sơ tạm: mỗi lần mở hộp một Idempotency-Key; bấm lại cùng nội dung dùng lại key (ADR-004), đổi nội dung thì key mới
  const sent = useRef<{ key: string; body: string } | null>(null);
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

  function keyFor(body: unknown): string {
    const sig = JSON.stringify(body);
    if (!sent.current) sent.current = { key: newIdempotencyKey(), body: sig };
    else if (sent.current.body !== sig) sent.current = { key: newIdempotencyKey(), body: sig };
    return sent.current.key;
  }

  // Gửi theo loại form; Sửa chỉ gửi trường đã đổi (không bao giờ gửi SĐT) kèm `version` (khóa lạc quan)
  function request() {
    if (mode.kind === "temp") {
      const body = { full_name: values.fullName, phone: values.phone, gender: values.gender || null };
      const key = keyFor(body);
      return callMemberApi(() => api.POST("/api/v1/members/temp", { body, headers: { "Idempotency-Key": key } }));
    }
    if (mode.kind === "add") {
      const key = keyFor(memberBody);
      return callMemberApi(() => api.POST("/api/v1/members", { body: memberBody, headers: { "Idempotency-Key": key } }));
    }
    const { fullName, gender, tier, isActive } = initial;
    const before: Record<string, unknown> = { full_name: fullName, gender: gender || null, tier: tier || null, racket: profile?.racket ?? null, is_active: isActive };
    // Hồ sơ tạm chỉ sửa tên + giới tính; Trạng thái chỉ Admin
    const editable = isMemberForm ? ["full_name", "gender", "tier", "racket", "is_active"] : ["full_name", "gender"];
    const isAllowed = (k: string) => editable.includes(k) && (canEditStatus || k !== "is_active");
    const changed = Object.fromEntries(
      Object.entries({ ...memberBody, is_active: values.isActive }).filter(([k, v]) => isAllowed(k) && before[k] !== v),
    );
    return callMemberApi(() => api.PATCH("/api/v1/members/{ref}", { params: { path: { ref: profile?.ref ?? "" } }, body: { ...changed, version: profile?.version ?? 0 } }));
  }

  async function save() {
    if (isPending) return;
    setIsPending(true);
    setError(null);
    setIsStale(false);
    const { data, error: apiError, response } = await request();
    setIsPending(false);
    if (data) return done(data as MemberRow);
    const failure = memberFailure(apiError, response, t.errors);
    if (failure.code === "E-MEM-4") {
      toast(failure.message, undefined, "error");
      return onClose();
    }
    // 409 E-MEM-9: đã sửa ở máy khác ⇒ không ghi đè, hiện câu + nút Tải lại
    if (failure.code === "E-MEM-9") return setIsStale(true);
    setError(failure);
  }

  // Toast ✓ (P5g / Thêm / Sửa) rồi đóng popup, tải lại danh sách
  function done(row: MemberRow | MemberCreated) {
    onSaved();
    // T-026: SĐT chưa có tài khoản ⇒ hộp thông báo mật khẩu ban đầu (không tự tắt); mật khẩu = SĐT đã nhập, API không trả
    if (mode.kind === "add" && "account_created" in row && row.account_created) {
      onAccountCreated({ row, phone: values.phone.replace(/\s+/g, ""), expiresAt: row.initial_password_expires_at });
      return;
    }
    toastSaved(mode.kind, row, t.toast);
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
      {isStale ? (
        <Alert variant="error">
          <span className="flex flex-wrap items-center justify-between gap-3">
            <span>{f.conflict}</span>
            <Button type="button" variant="secondary" onClick={onReload}>
              {f.reload}
            </Button>
          </span>
        </Alert>
      ) : null}
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
          setValues((v) => ({ ...v, ...patch }));
        }}
        withMemberFields={isMemberForm}
        phoneNote={mode.kind === "add" ? f.accountNote : undefined}
        withStatus={mode.kind === "edit" && isMemberForm}
        isStatusLocked={!canEditStatus}
        isPhoneLocked={mode.kind === "edit"}
        racketNames={rackets.status === "ok" ? rackets.items.map((r) => r.name) : []}
        error={error}
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
function toastSaved(kind: "add" | "temp" | "edit", row: MemberRow | MemberCreated, t: Dictionary["members"]["toast"]) {
  const memberSub = (row.tier ? t.memberSub : t.memberSubNoTier)
    .replace("{name}", row.full_name)
    .replace("{code}", row.member_code ?? "")
    .replace("{tier}", row.tier ?? "");
  const tempSub = t.tempSub.replace("{name}", row.full_name).replace("{phone}", formatPhone(row.phone));
  if (kind === "temp") toast(t.tempCreated, tempSub);
  else if (kind === "edit") toast(t.saved, row.kind === "member" ? memberSub : tempSub);
  else if ("account_created" in row && row.account_created === false) toast(t.addedExisting.replace("{code}", row.member_code ?? ""), t.addedExistingSub);
  else toast(t.added, memberSub);
}
