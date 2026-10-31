"use client";

import { useId, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { CheckIcon, LoaderIcon, PlusIcon } from "@/components/ui/icons";
import { Modal } from "@/components/ui/modal";
import { Skeleton } from "@/components/ui/skeleton";
import type { Dictionary } from "@/i18n/dictionaries";
import type { MemberDetail } from "@/lib/api/server";
import { cn } from "@/lib/cn";
import { formatPhone } from "@/lib/phone";
import { FormBody } from "./member-form-body";
import { EMPTY_MEMBER, valuesOf } from "./member-form-fields";
import { useMemberDetail } from "./use-member-detail";

// Sửa dùng chung cho hội viên và hồ sơ tạm (loại lấy từ chi tiết)
export type FormMode = { kind: "add" } | { kind: "temp" } | { kind: "edit"; ref: string; detail?: MemberDetail };

type Props = {
  mode: FormMode;
  canEditStatus: boolean;
  onClose: () => void;
  /** Lưu xong (hoặc hồ sơ đã đổi ở nơi khác) ⇒ tải lại danh sách. */
  onSaved: () => void;
  t: Dictionary["members"];
};

/** Popup Thêm hội viên (P5a) / Sửa hội viên (P5b) / Tạo hồ sơ tạm (P5f) / Sửa hồ sơ tạm. */
export function MemberForm({ mode, canEditStatus, onClose, onSaved, t }: Props) {
  const f = t.form;
  const isEdit = mode.kind === "edit";
  // Tải lại sau 409 E-MEM-9: bỏ chi tiết có sẵn (đã cũ), lấy bản mới nhất từ server
  const [reloadKey, setReloadKey] = useState(0);
  const state = useMemberDetail(isEdit ? mode.ref : null, isEdit && reloadKey === 0 ? mode.detail : undefined, reloadKey);
  const detail = isEdit && state.status === "ok" ? state.detail : null;
  const title =
    mode.kind === "add" ? f.addTitle
    : mode.kind === "temp" ? t.temp.title
    : detail?.kind === "temp" ? f.editTempTitle
    : f.editTitle.replace("{code}", detail?.member_code ?? "");
  // Trạng thái đang lưu nằm ở đây vì nút Lưu ở chân popup (ngoài <form>, nối bằng form={formId})
  const formId = useId();
  const [isPending, setIsPending] = useState(false);
  const isFormShown = !isEdit || detail !== null;

  return (
    <Modal
      open
      onClose={onClose}
      title={title}
      size="wide"
      footer={
        isFormShown ? (
          <FormFooter
            formId={formId}
            isPending={isPending}
            icon={mode.kind === "edit" ? "save" : "add"}
            submitLabel={mode.kind === "temp" ? t.temp.submit : mode.kind === "edit" ? f.saveEdit : f.saveNew}
            onCancel={onClose}
            t={f}
          />
        ) : undefined
      }
    >
      {isEdit && state.status === "error" ? <Alert variant="error">{f.loadError}</Alert> : null}
      {isEdit && state.status === "loading" ? <FormSkeleton label={f.loading} /> : null}
      {isFormShown ? (
        <FormBody
          // Bản mới (version đổi) ⇒ dựng form mới từ dữ liệu mới
          key={detail?.version ?? 0}
          id={formId}
          isPending={isPending}
          setIsPending={setIsPending}
          mode={mode}
          // Sửa: SĐT đầy đủ, chỉ xem (cả hồ sơ tạm)
          initial={detail ? valuesOf(detail, formatPhone(detail.phone)) : EMPTY_MEMBER}
          profile={detail}
          canEditStatus={canEditStatus}
          onClose={onClose}
          onSaved={onSaved}
          onReload={() => {
            setReloadKey((k) => k + 1);
            onSaved();
          }}
          t={t}
        />
      ) : null}
    </Modal>
  );
}

type FooterProps = {
  /** id của <form>: nút Lưu nằm ở chân popup, ngoài form. */
  formId: string;
  isPending: boolean;
  /** Icon nút chính: thêm mới (+) hay lưu sửa (✓). */
  icon: "add" | "save";
  submitLabel: string;
  onCancel: () => void;
  t: Dictionary["members"]["form"];
};

/** Nút ở chân popup (slot footer của Modal); điện thoại nút chính rộng hết hàng, nằm dưới cùng. */
function FormFooter({ formId, isPending, icon, submitLabel, onCancel, t }: FooterProps) {
  return (
    <div className="flex w-full flex-col-reverse gap-2 sm:flex-row sm:justify-end">
      <Button type="button" variant="secondary" onClick={onCancel}>
        {t.cancel}
      </Button>
      <Button type="submit" form={formId} loading={isPending}>
        {isPending ? <LoaderIcon /> : icon === "save" ? <CheckIcon /> : <PlusIcon />}
        {isPending ? t.saving : submitLabel}
      </Button>
    </div>
  );
}

// Khung tải khi mở Sửa mà chưa có chi tiết: các ô nhập giả
function FormSkeleton({ label }: { label: string }) {
  return (
    <div className="flex flex-col gap-4">
      <p role="status" className="sr-only">
        {label}
      </p>
      {["w-24", "w-20", "w-28"].map((w) => (
        <div key={w} className="flex flex-col gap-1.5">
          <Skeleton className={cn("h-3", w)} />
          <Skeleton className="h-11 rounded-lg sm:h-9.5" />
        </div>
      ))}
    </div>
  );
}
