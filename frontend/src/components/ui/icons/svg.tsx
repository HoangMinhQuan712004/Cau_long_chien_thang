export type IconProps = React.SVGProps<SVGSVGElement> & { size?: number };

/** Khung chung: nét `currentColor`, ẩn với trình đọc màn hình (nghĩa nằm ở chữ bên cạnh). Nét theo prototype. */
export function Svg({ size = 18, children, ...props }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      focusable={false}
      {...props}
    >
      {children}
    </svg>
  );
}
