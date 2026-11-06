import { AvatarImage } from "@/components/ui/avatar";
import { ShuttlecockIcon } from "@/components/ui/icons";
import { cn } from "@/lib/cn";

type Props = {
  /** Logo đã tải lên (ảnh vuông do server cắt); chưa có hoặc ảnh lỗi ⇒ icon quả cầu lông. */
  url?: string | null;
  /** Trên nền xanh đậm (header quản trị): ô trắng, icon xanh để nổi trên nền. */
  onDark?: boolean;
  /** Cỡ ô, vd `size-8`. */
  className?: string;
};

/** Logo web dùng chung: ô vuông bo góc đứng cạnh tên chữ; trang trí nên ẩn với trình đọc màn hình. */
export function SiteLogo({ url, onDark = false, className }: Props) {
  return (
    <span
      aria-hidden
      className={cn(
        "grid shrink-0 place-items-center overflow-hidden rounded-lg",
        // Có ảnh: luôn nền trắng để logo nền trong suốt không phụ thuộc màu header
        url || onDark ? "bg-surface text-primary" : "bg-primary text-surface",
        className,
      )}
    >
      <AvatarImage url={url} fallback={<ShuttlecockIcon size={20} />} />
    </span>
  );
}
