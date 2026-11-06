import { type IconProps, Svg } from "./svg";

// Icon đối tượng (người, liên lạc, thời gian), nét chép từ Lucide (giấy phép ISC)
export function UserIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </Svg>
  );
}

export function UserPlusIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M19 8v6M22 11h-6" />
    </Svg>
  );
}

export function UserCheckIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="m16 11 2 2 4-4" />
    </Svg>
  );
}

export function PhoneIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.8 19.8 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.8 19.8 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.8 12.8 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.8 12.8 0 0 0 2.81.7A2 2 0 0 1 22 16.92z" />
    </Svg>
  );
}

export function CalendarIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M8 2v4M16 2v4M3 10h18" />
      <rect x="3" y="4" width="18" height="18" rx="2" />
    </Svg>
  );
}

export function ClockIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="10" />
      <path d="M12 6v6l4 2" />
    </Svg>
  );
}

/** Vợt cầu lông: mặt vợt bầu dục có lưới, cán chéo xuống trái (tự vẽ cùng kiểu nét Lucide). */
/** Quả cầu lông nghiêng 45° (vẽ riêng cho dự án): váy lông xòe lên phải, đế tròn dưới trái. Logo mặc định của web. */
export function ShuttlecockIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <g transform="rotate(45 12 12)">
        <path d="M9.6 15.5 6 3.5h12l-3.6 12" />
        <path d="M12 3.5v12" />
        <path d="M7.6 9.5h8.8" />
        <path d="M9.6 15.5h4.8v2.1a2.4 2.4 0 0 1-4.8 0z" fill="currentColor" />
      </g>
    </Svg>
  );
}

export function RacketIcon(props: IconProps) {
  return (
    <Svg {...props}>
      <ellipse cx="15" cy="9" rx="5.5" ry="6.5" transform="rotate(45 15 9)" />
      <path d="M11.2 12.8 4.5 19.5M3.5 20.5l1-1" />
      <path d="M12.5 8.5l3 3M14.5 6.5l3 3M11 11l2 2M12.2 6.8l-1.5 4.4M15 5.3l-3.2 6.4M17.7 6.3l-3.4 6.4" opacity={0.6} />
    </Svg>
  );
}
