import { cn } from "@/lib/cn";

/** Ảnh đại diện tròn; chưa có ảnh → chữ cái đầu của tên ngắn trên nền xanh (BR-014). */
export function Avatar({ url, name, size, className }: { url: string | null; name: string; size: number; className?: string }) {
  const letter = (name.trim().charAt(0) || "?").toLocaleUpperCase("vi");
  return (
    <span
      aria-hidden
      // Cỡ px quy ra rem: co giãn theo chữ gốc của trang (màn có chữ gốc co giãn – `data-fluid-text`)
      style={{ width: `${size / 16}rem`, height: `${size / 16}rem`, fontSize: `${(size * 0.42) / 16}rem` }}
      className={cn("grid shrink-0 place-items-center overflow-hidden rounded-full bg-primary font-bold text-surface select-none", className)}
    >
      {url ? (
        // eslint-disable-next-line @next/next/no-img-element -- ảnh đã được server cắt vuông / thu nhỏ; URL có ?v= theo etag
        <img src={url} alt="" width={size} height={size} className="size-full object-cover" />
      ) : (
        letter
      )}
    </span>
  );
}
