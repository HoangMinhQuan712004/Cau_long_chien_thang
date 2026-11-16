"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { fieldErrorId } from "@/components/ui/field";
import { IconButton } from "@/components/ui/icon-button";
import { PencilIcon } from "@/components/ui/icons";
import { Input } from "@/components/ui/input";
import type { Dictionary } from "@/i18n/dictionaries";
import { api, errorMessage } from "@/lib/api/client";
import { cn } from "@/lib/cn";
import { toast } from "@/lib/feedback";
import { FORM_ACTIONS } from "./profile-sheet";

// Cùng giới hạn với backend (AdminProfileIn.full_name: 1–50 ký tự)
const NAME_MAX = 50;
const len = (v: string) => [...v].length;

/** Cắt về NAME_MAX ký tự: giá trị ban đầu + lưới cuối sau khi gõ IME xong. */
const clampName = (v: string) => (len(v) <= NAME_MAX ? v : [...v].slice(0, NAME_MAX).join(""));

/** Số ký tự còn chèn được: 50 − (độ dài − đoạn đang chọn/bị thay); gõ đè lên đoạn chọn vẫn được. */
function room(el: HTMLInputElement): number {
  const selected = el.value.slice(el.selectionStart ?? 0, el.selectionEnd ?? 0);
  return NAME_MAX - (len(el.value) - len(selected));
}

/** Họ tên + nhãn vai trò; Admin bấm bút để sửa tại chỗ (Enter lưu, Esc hủy), NV chỉ xem. */
export function ProfileName({ name, roleLabel, isAdmin, t }: { name: string; roleLabel: string; isAdmin: boolean; t: Dictionary["adminProfile"] }) {
  const router = useRouter();
  const [isEditing, setIsEditing] = useState(false);
  const [value, setValue] = useState(() => clampName(name));
  const [error, setError] = useState<string | null>(null);
  const [isPending, setIsPending] = useState(false);
  const trimmed = value.trim();
  const count = len(value);
  // Đang soạn IME (Telex/VNI); compositionend cắt lại về 50 làm lưới cuối
  const composing = useRef(false);
  // Bị chặn vì đủ 50: khung rung, viền/vòng focus/bộ đếm đỏ 500ms, đọc "Đã đủ 50 ký tự" một lần mỗi lần chạm giới hạn
  const shakeRef = useRef<HTMLDivElement>(null);
  const flashTimer = useRef(0);
  const [isFlash, setIsFlash] = useState(false);
  const [isAnnounced, setIsAnnounced] = useState(false);
  const block = useCallback(() => {
    const box = shakeRef.current;
    // Gỡ rồi gắn lại class để lần nào cũng rung (className khung này không do React đổi)
    box?.classList.remove("animate-shake");
    void box?.offsetWidth;
    box?.classList.add("animate-shake");
    setIsFlash(true);
    window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setIsFlash(false), 500);
    setIsAnnounced(true);
  }, []);
  useEffect(() => () => window.clearTimeout(flashTimer.current), []);
  const countTone = isFlash ? "font-semibold text-danger" : count >= NAME_MAX ? "font-semibold text-accent-fg" : "text-muted";

  // Chặn từ gốc: chèn chữ mà độ dài sau khi chèn vượt 50 ⇒ hủy (chỉ xét độ dài nên xóa lùi rồi chèn "á" vẫn thêm dấu được); soạn IME do onChange lo
  useEffect(() => {
    if (!isEditing) return;
    const el = document.getElementById("profile-name") as HTMLInputElement | null;
    if (!el) return;
    const onBeforeInput = (e: InputEvent) => {
      if (!e.inputType.startsWith("insert") || e.inputType === "insertCompositionText" || !e.cancelable) return;
      const data = e.data ?? e.dataTransfer?.getData("text/plain") ?? "";
      if (len(data) <= room(el)) return;
      e.preventDefault();
      block();
    };
    el.addEventListener("beforeinput", onBeforeInput);
    return () => el.removeEventListener("beforeinput", onBeforeInput);
  }, [isEditing, block]);

  // Dán: chỉ chèn phần còn chỗ tại con trỏ
  function onPaste(e: React.ClipboardEvent<HTMLInputElement>) {
    e.preventDefault();
    const el = e.currentTarget;
    const all = [...e.clipboardData.getData("text").replace(/\s+/g, " ")];
    const part = all.slice(0, Math.max(0, room(el))).join("");
    if (all.length > len(part)) block();
    if (!part) return;
    el.setRangeText(part, el.selectionStart ?? el.value.length, el.selectionEnd ?? el.value.length, "end");
    setValue(clampName(el.value));
    setError(null);
  }

  function cancel() {
    setIsEditing(false);
    setValue(clampName(name));
    setError(null);
  }

  async function onSubmit(e: React.SubmitEvent<HTMLFormElement>) {
    e.preventDefault();
    if (isPending) return;
    if (!trimmed) return setError(t.nameRequired);
    if (trimmed === name) return cancel();
    setIsPending(true);
    setError(null);
    try {
      const { error: err, response } = await api.PATCH("/api/v1/admin/account", { body: { full_name: trimmed } });
      if (response.ok) {
        toast(t.nameSaved);
        setIsEditing(false);
        router.refresh(); // header + trang lấy tên mới
        return;
      }
      // 401 hết phiên: middleware của client đã chuyển về màn đăng nhập
      if (response.status !== 401) setError(errorMessage(err, t.unavailable));
    } catch {
      setError(t.network);
    } finally {
      setIsPending(false);
    }
  }

  if (!isEditing) {
    return (
      <div className="flex min-w-0 flex-1 flex-col items-start gap-2">
        {/* Tên dài không dấu cách vẫn xuống dòng trong thẻ; bút luôn ngay sau tên, căn dòng đầu */}
        <div className="flex max-w-full min-w-0 items-start gap-1">
          <h2 className={cn(`min-w-0 text-xl/8 font-bold tracking-tight wrap-anywhere sm:text-2xl/8`)}>{name}</h2>
          {isAdmin ? (
            <IconButton icon={<PencilIcon />} label={`${t.editName}: ${name}`} tooltip={t.editName} onClick={() => setIsEditing(true)} />
          ) : null}
        </div>
        <Badge variant={isAdmin ? "warning" : "success"} className="px-3 py-1">{roleLabel}</Badge>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex min-w-0 flex-1 flex-col gap-2">
      <label htmlFor="profile-name" className="text-label font-semibold text-muted">{t.nameLabel}</label>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
        <div className="min-w-0 flex-1">
          {/* Khung ngoài chỉ để rung (class gắn bằng tay); khung trong chớp đỏ viền + vòng focus (ghi đè focus-ring, cùng độ nhạt 28%) */}
          <div ref={shakeRef} onAnimationEnd={(e) => e.currentTarget.classList.remove("animate-shake")}>
          <div className={cn(
            isFlash && `
              [&_input]:border-danger
              [&_input:focus-visible]:[box-shadow:0_0_0_3px_color-mix(in_srgb,var(--danger)_28%,transparent)]
            `,
          )}>
          <Input
            id="profile-name"
            value={value}
            onChange={(e) => {
              const next = e.target.value;
              setError(null);
              // Vượt 50 khi đang soạn IME: không nhận, ô (controlled) giữ giá trị cũ ⇒ phần dư không hiện ra
              if (len(next) > NAME_MAX) {
                block();
                if (!composing.current) setValue(clampName(next));
                return;
              }
              if (len(next) < NAME_MAX) setIsAnnounced(false);
              setValue(next);
            }}
            onCompositionStart={() => (composing.current = true)}
            onCompositionEnd={(e) => {
              composing.current = false;
              setValue(clampName(e.currentTarget.value));
            }}
            onKeyDown={(e) => e.key === "Escape" && cancel()}
            onPaste={onPaste}
            readOnly={isPending}
            maxLength={NAME_MAX}
            autoComplete="name"
            autoFocus
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? `${fieldErrorId("profile-name")} profile-name-count` : "profile-name-count"}
          />
          </div>
          </div>
          <div className="mt-1.5 flex items-start justify-between gap-3 text-ui">
            {error ? <p id={fieldErrorId("profile-name")} className="text-danger">{error}</p> : <span />}
            <p id="profile-name-count" className={cn("shrink-0 tabular-nums transition-colors", countTone)}>
              {count}/{NAME_MAX}
            </p>
            {/* Trình đọc màn hình: báo một lần mỗi khi chạm giới hạn */}
            <span aria-live="polite" className="sr-only">{isAnnounced && count >= NAME_MAX ? t.nameFull : ""}</span>
          </div>
        </div>
        <div className={FORM_ACTIONS}>
          <Button type="submit" loading={isPending} disabled={!trimmed}>{isPending ? t.submitting : t.save}</Button>
          <Button type="button" variant="secondary" onClick={cancel} disabled={isPending}>{t.cancel}</Button>
        </div>
      </div>
    </form>
  );
}
