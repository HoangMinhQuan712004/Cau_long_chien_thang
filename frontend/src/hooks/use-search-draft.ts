"use client";

import { useEffect, useRef, useState } from "react";

/** Ô tìm: giữ chữ đang gõ, ngừng gõ `delayMs` mới áp; giá trị đổi từ ngoài (vd "Xóa lọc") ⇒ ô theo, không ghi lại chữ cũ. */
export function useSearchDraft(value: string, onChange: (value: string) => void, delayMs = 350) {
  const [draft, setDraft] = useState(value);
  const [synced, setSynced] = useState(value);
  if (value !== synced) {
    setSynced(value);
    setDraft(value);
  }
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  });
  useEffect(() => {
    if (draft === value) return;
    const timer = setTimeout(() => onChangeRef.current(draft), delayMs);
    return () => clearTimeout(timer);
  }, [draft, value, delayMs]);
  return [draft, setDraft] as const;
}
