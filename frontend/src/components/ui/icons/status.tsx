import { cn } from "@/lib/cn";
import { type IconProps, Svg } from "./svg";

// Icon trạng thái: thông báo, quy tắc mật khẩu, câu rỗng, đang tải
export function AlertCircleIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7.5v5.5M12 16.5v.1" />
    </Svg>
  );
}

export function InfoIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v6M12 7.5v.1" />
    </Svg>
  );
}

export function CheckCircleIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12.5l2.7 2.7L16 9.8" />
    </Svg>
  );
}

export function CircleIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="9" />
    </Svg>
  );
}


/** Danh sách trống (Lucide inbox). */
export function InboxIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M22 12h-6l-2 3h-4l-2-3H2" />
      <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
    </Svg>
  );
}

/** Tìm không ra kết quả (Lucide search-x). */
export function SearchXIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="m13.5 8.5-5 5M8.5 8.5l5 5M21 21l-4.3-4.3" />
      <circle cx="11" cy="11" r="8" />
    </Svg>
  );
}

/** Vòng đang tải tự xoay (Lucide loader-circle); giảm chuyển động ⇒ đứng yên, cần chữ "Đang…" bên cạnh. */
export function LoaderIcon({ className, ...props }: IconProps) {
  return (
    <Svg className={cn("animate-spin motion-reduce:animate-none", className)} {...props}>
      <path d="M21 12a9 9 0 1 1-6.22-8.56" />
    </Svg>
  );
}
