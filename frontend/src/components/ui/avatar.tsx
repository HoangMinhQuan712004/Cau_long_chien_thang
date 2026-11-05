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

/** Ảnh đại diện tròn bằng chữ cái đầu của tên; trang trí (tên đã có chữ bên cạnh) nên ẩn với trình đọc màn hình. */
export function Avatar({ name, size = "md" }: { name: string; /** "sm": 32px, dùng trong dòng bảng / thẻ. */ size?: "sm" | "md" }) {
  return (
    <span aria-hidden // md: điện thoại 44px, từ sm 56px; sm: 32px
      className={cn(
        "grid shrink-0 place-items-center rounded-full font-bold",
        size === "sm" ? "size-8 text-sm" : "size-11 text-base sm:size-14 sm:text-xl",
        toneOf(name),
      )}>
      {initialOf(name)}
    </span>
  );
}
