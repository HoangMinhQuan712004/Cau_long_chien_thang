"use client";

import Image from "next/image";
import { useState } from "react";
import { cn } from "@/lib/cn";

// Cặp nền nhạt / chữ đậm từ token sẵn có (không thêm màu mới)
const TONES = [
  "bg-primary-soft text-primary-hover",
  "bg-info-soft text-info",
  "bg-accent-soft text-accent-fg",
  "bg-danger-soft text-danger",
] as const;

// Cùng tên ⇒ cùng màu (băm đơn giản theo mã ký tự)
function toneOf(name: string): string {
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + (ch.codePointAt(0) ?? 0)) >>> 0;
  return TONES[hash % TONES.length];
}

// Tên người Việt gọi bằng chữ cuối ("Nguyễn Văn An" ⇒ "A")
function initialOf(name: string): string {
  const last = name.trim().split(/\s+/).pop() ?? "";
  return last.charAt(0).toLocaleUpperCase("vi") || "?";
}

/** Ảnh nếu có; chưa có ảnh hoặc ảnh lỗi ⇒ `fallback`. Nơi gọi tự lo khung tròn (`overflow-hidden`). `unoptimized`: ảnh đã do server cắt, cần cookie phiên. */
export function AvatarImage({ url, fallback }: { url?: string | null; fallback: React.ReactNode }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  if (!url || url === failedUrl) return fallback;
  return <Image src={url} alt="" width={96} height={96} unoptimized onError={() => setFailedUrl(url)} className="
    size-full object-cover
  " />;
}

/** Ảnh đại diện tròn: có ảnh thì hiện ảnh, không thì chữ cái đầu của tên; trang trí (tên đã có chữ bên cạnh) nên ẩn với trình đọc màn hình. */
export function Avatar({ name, url, size = "md" }: { name: string; url?: string | null; /** "sm": 32px, dùng trong dòng bảng / thẻ. */ size?: "sm" | "md" }) {
  return (
    <span aria-hidden // md: điện thoại 44px, từ sm 56px; sm: 32px
      className={cn(
        "grid shrink-0 place-items-center overflow-hidden rounded-full font-bold",
        size === "sm" ? "size-8 text-sm" : "size-11 text-base sm:size-14 sm:text-xl",
        toneOf(name),
      )}>
      <AvatarImage url={url} fallback={initialOf(name)} />
    </span>
  );
}
