import { type IconProps, Svg } from "./svg";

// Icon thao tác và điều hướng nhỏ (nét chép từ Lucide, giấy phép ISC)
export function EyeIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" />
      <circle cx="12" cy="12" r="3" />
    </Svg>
  );
}

export function EyeOffIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3 3.8M6.3 6.3C3.6 8.1 2 12 2 12s3.6 7 10 7a9.7 9.7 0 0 0 4.2-.9M9.9 9.9a3 3 0 0 0 4.2 4.2" />
    </Svg>
  );
}

export function ChevronDownIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M6 9l6 6 6-6" />
    </Svg>
  );
}

export function ChevronLeftIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M15 18l-6-6 6-6" />
    </Svg>
  );
}

export function ChevronRightIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M9 18l6-6-6-6" />
    </Svg>
  );
}

export function SearchIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-3.5-3.5" />
    </Svg>
  );
}

export function CloseIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M18 6L6 18M6 6l12 12" />
    </Svg>
  );
}

export function MenuIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M4 6h16M4 12h16M4 18h16" />
    </Svg>
  );
}


export function PlusIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M5 12h14M12 5v14" />
    </Svg>
  );
}

export function PencilIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M21.17 6.81a1 1 0 0 0-3.98-3.99L3.84 16.17a2 2 0 0 0-.5.83l-1.32 4.36a.5.5 0 0 0 .62.62l4.35-1.32a2 2 0 0 0 .83-.5z" />
      <path d="m15 5 4 4" />
    </Svg>
  );
}

export function TrashIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M3 6h18M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2M10 11v6M14 11v6" />
    </Svg>
  );
}

/** Xóa lọc / làm lại (Lucide rotate-ccw). */
export function ResetIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
      <path d="M3 3v5h5" />
    </Svg>
  );
}

// Mũi tên cột sắp xếp: chưa sắp / tăng / giảm
export function ArrowUpDownIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="m21 16-4 4-4-4M17 20V4M3 8l4-4 4 4M7 4v16" />
    </Svg>
  );
}

export function ArrowUpIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="m5 12 7-7 7 7M12 19V5" />
    </Svg>
  );
}

export function ArrowDownIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 5v14M19 12l-7 7-7-7" />
    </Svg>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M20 6 9 17l-5-5" />
    </Svg>
  );
}

/** Thu gọn / mở rộng menu bên (Lucide panel-left). */
export function PanelLeftIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M9 3v18" />
    </Svg>
  );
}

/** Lịch sử thao tác (Lucide history). */
export function HistoryIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
      <path d="M3 3v5h5M12 7v5l4 2" />
    </Svg>
  );
}

/** Đăng xuất (Lucide log-out). */
export function LogOutIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />
    </Svg>
  );
}
