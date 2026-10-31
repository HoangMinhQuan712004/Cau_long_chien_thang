"use client";

import { useState } from "react";
import type { Dictionary } from "@/i18n/dictionaries";
import type { AuditEntry } from "@/lib/api/server";
import { formatPhone } from "@/lib/phone";

type Props = { changes: AuditEntry["changes"]; t: Dictionary["auditLog"] };

/** Hiện tối đa 3 ô; nhiều hơn ⇒ "Xem thêm (n)" mở ngay tại dòng, "Thu gọn" về 3 ô (BR-006). */
const COLLAPSED = 3;

// Giá trị ô: tạo mới ⇒ "(trống)"; SĐT 10 số ⇒ định dạng nhóm số, vẫn đầy đủ (BR-007)
function show(value: AuditEntry["changes"][number]["before"], t: Dictionary["auditLog"]): string {
  if (value === null || value === undefined || value === "") return t.empty;
  const text = String(value);
  return /^0\d{9}$/.test(text) ? formatPhone(text) : text;
}

/** Cột "Giá trị trước → sau": mỗi ô đã đổi một dòng "Tên ô: trước → sau"; không có ⇒ "—". */
export function AuditChanges({ changes, t }: Props) {
  const [isOpen, setIsOpen] = useState(false);
  if (changes.length === 0) return <span className="text-muted">{t.noValue}</span>;
  const hidden = changes.length - COLLAPSED;
  // Đúng 4 ô cũng gom (docs: "từ 4 ô trở lên") ⇒ luôn có ít nhất 1 ô ẩn khi > 3
  const shown = isOpen || hidden <= 0 ? changes : changes.slice(0, COLLAPSED);

  return (
    <div className="flex flex-col gap-0.5">
      <ul className="flex flex-col gap-0.5">
        {shown.map((c, i) => (
          <li key={`${c.field}-${i}`} className="wrap-break-word">
            <span className="text-muted">{c.field}: </span>
            <span>{show(c.before, t)}</span>
            <span aria-hidden className="px-1 text-muted">
              →
            </span>
            <span className="sr-only"> {t.becomes} </span>
            <span className="font-medium">{show(c.after, t)}</span>
          </li>
        ))}
      </ul>
      {hidden > 0 ? (
        <button
          type="button"
          aria-expanded={isOpen}
          onClick={() => setIsOpen((v) => !v)}
          className="self-start rounded-sm font-semibold text-primary focus-ring hover:underline"
        >
          {isOpen ? t.less : t.more.replace("{n}", String(hidden))}
        </button>
      ) : null}
    </div>
  );
}
