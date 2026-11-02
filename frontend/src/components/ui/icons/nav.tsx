import { type IconProps, Svg } from "./svg";

// Icon menu quản trị 20px nét 2 (Figma Sidebar 205:8718); mục chưa có trong Figma vẽ cùng kiểu lucide
function Nav20({ children, ...props }: IconProps) {
  return (
    <Svg size={20} viewBox="0 0 20 20" strokeWidth={2} {...props}>
      {children}
    </Svg>
  );
}

// Lưới 24 thu về 20px: nét 2.4 để dày bằng icon Figma
function Nav24({ children, ...props }: IconProps) {
  return (
    <Svg size={20} strokeWidth={2.4} {...props}>
      {children}
    </Svg>
  );
}

export function CalendarPlusIcon(props: IconProps) {
  return (
    <Nav20 {...props}>
      <path d="M13.33 15h5M13.33 1.67v2.5M15.83 12.5v5M2.5 7.5h15M6.67 1.67v2.5" />
      <path d="M17.5 9.58V4.17c0-.92-.75-1.67-1.67-1.67H4.17c-.92 0-1.67.75-1.67 1.67v11.66c0 .92.75 1.67 1.67 1.67h6.91" />
    </Nav20>
  );
}

export function ReceiptIcon(props: IconProps) {
  return (
    <Nav24 {...props}>
      <path d="M4 2v20l2-1 2 1 2-1 2 1 2-1 2 1 2-1 2 1V2l-2 1-2-1-2 1-2-1-2 1-2-1-2 1Z" />
      <path d="M16 8h-6a2 2 0 1 0 0 4h4a2 2 0 1 1 0 4H8M12 17.5v-11" />
    </Nav24>
  );
}

export function UsersIcon(props: IconProps) {
  return (
    <Nav20 {...props}>
      <path d="M13.33 17.5v-1.67a3.33 3.33 0 0 0-3.33-3.33H5a3.33 3.33 0 0 0-3.33 3.33v1.67" />
      <path d="M13.33 2.6a3.33 3.33 0 0 1 0 6.46M18.33 17.5v-1.67a3.33 3.33 0 0 0-2.5-3.22" />
      <circle cx="7.5" cy="5.83" r="3.33" />
    </Nav20>
  );
}

export function SettingsIcon(props: IconProps) {
  return (
    <Nav20 {...props}>
      <path d="M8.06 3.45a1.95 1.95 0 0 1 3.88 0 1.95 1.95 0 0 0 2.77 1.6 1.95 1.95 0 0 1 1.94 3.36 1.95 1.95 0 0 0 0 3.19 1.95 1.95 0 0 1-1.94 3.36 1.95 1.95 0 0 0-2.77 1.6 1.95 1.95 0 0 1-3.88 0 1.95 1.95 0 0 0-2.77-1.6 1.95 1.95 0 0 1-1.94-3.36 1.95 1.95 0 0 0 0-3.19 1.95 1.95 0 0 1 1.94-3.36 1.95 1.95 0 0 0 2.77-1.6" />
      <circle cx="10" cy="10" r="2.5" />
    </Nav20>
  );
}

export function WalletIcon(props: IconProps) {
  return (
    <Nav24 {...props}>
      <path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1" />
      <path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4" />
    </Nav24>
  );
}

export function CreditCardIcon(props: IconProps) {
  return (
    <Nav24 {...props}>
      <rect x="2" y="5" width="20" height="14" rx="2" />
      <path d="M2 10h20" />
    </Nav24>
  );
}

export function IdCardIcon(props: IconProps) {
  return (
    <Nav24 {...props}>
      <rect x="2" y="5" width="20" height="14" rx="2" />
      <circle cx="9" cy="11" r="2" />
      <path d="M16 10h2M16 14h2M6.17 15a3 3 0 0 1 5.66 0" />
    </Nav24>
  );
}

export function MoreVerticalIcon(props: IconProps) {
  return (
    <Nav20 {...props}>
      <circle cx="10" cy="4.17" r=".83" />
      <circle cx="10" cy="10" r=".83" />
      <circle cx="10" cy="15.83" r=".83" />
    </Nav20>
  );
}

// Báo cáo & phân tích: biểu đồ cột (lucide chart-column)
export function ChartIcon(props: IconProps) {
  return (
    <Nav24 {...props}>
      <path d="M3 3v16a2 2 0 0 0 2 2h16M18 17V9M13 17V5M8 17v-3" />
    </Nav24>
  );
}
