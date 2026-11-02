/** Banner xanh đậm đầu trang khu hội viên (tiêu đề + dòng phụ + vùng bên phải), có hình sân mờ. */
export function PageBanner({ title, subtitle, aside, children, desktopOnly = false }: { title: string; subtitle?: React.ReactNode; aside?: React.ReactNode; children?: React.ReactNode; desktopOnly?: boolean }) {
  return (
    // Dưới lg tiêu đề do app bar của khung hiển thị (T-028 AC3); không có điều khiển nào thì ẩn cả banner
    <section className={`relative overflow-hidden bg-appbar text-surface ${aside || children ? "" : "max-lg:hidden"} ${desktopOnly ? "max-lg:hidden" : ""}`}>
      <svg aria-hidden viewBox="0 0 320 160" className="pointer-events-none absolute -top-2 left-1/2 hidden h-full max-h-48 text-surface opacity-10 md:block" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="20" y="10" width="280" height="140" />
        <path d="M160 10v140M20 80h280M20 40h280M20 120h280M90 10v140M230 10v140" />
      </svg>
      <div className="relative mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 px-4 py-6 sm:py-8">
        <div className="min-w-0 max-lg:sr-only">
          <h1 className="text-2xl font-bold break-words sm:text-3xl">{title}</h1>
          {subtitle ? <p className="mt-1 text-sm text-surface/80">{subtitle}</p> : null}
        </div>
        {aside}
      </div>
      {children}
    </section>
  );
}
