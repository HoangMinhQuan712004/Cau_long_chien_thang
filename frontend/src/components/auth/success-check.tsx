/** Vòng tròn + dấu tick tự vẽ, báo đổi mật khẩu thành công (Quên mật khẩu, Đổi mật khẩu lần đầu). */
export function SuccessCheck({ label }: { label: string }) {
  return (
    <div role="status" aria-live="polite" className="flex flex-col items-center gap-3 py-6 text-primary">
      <svg aria-hidden viewBox="0 0 52 52" className="size-16" fill="none" stroke="currentColor">
        <circle
          cx="26"
          cy="26"
          r="23"
          strokeWidth="3"
          strokeLinecap="round"
          pathLength="1"
          transform="rotate(-90 26 26)"
          className="animate-draw"
        />
        <path
          d="M15 27l7.5 7.5L37.5 19"
          strokeWidth="4"
          strokeLinecap="round"
          strokeLinejoin="round"
          pathLength="1"
          style={{ animationDelay: "350ms" }}
          className="animate-draw"
        />
      </svg>
      <p className="font-semibold text-foreground">{label}</p>
    </div>
  );
}
