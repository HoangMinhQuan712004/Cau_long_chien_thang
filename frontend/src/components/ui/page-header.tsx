import { cn } from "@/lib/cn";
import { ActionMenu, type MenuAction } from "./action-menu";
import { Button } from "./button";

type PageHeaderProps = {
  title: React.ReactNode;
  /** Dòng phụ dưới tiêu đề (vd tóm tắt số liệu); có thể là Skeleton khi đang tải. */
  description?: React.ReactNode;
  /** Dòng phụ luôn nằm dưới tiêu đề (câu giải thích dài), thay vì cùng dòng. */
  descriptionBelow?: boolean;
  /** Nút chính: luôn có icon + chữ. */
  primaryAction?: MenuAction;
  /** Nút phụ: từ sm là nút viền; điện thoại gom vào menu ⋯ cho đầu trang gọn. */
  actions?: readonly MenuAction[];
  /** Tên nút ⋯ ("Thao tác khác"). */
  moreLabel?: string;
  /** Nội dung tự do bên phải thay cho các nút (vd khung giữ chỗ khi tải). */
  aside?: React.ReactNode;
  /** Nút chỉ hiện ở đầu trang trên điện thoại; từ sm nơi gọi tự đặt PageActions chỗ khác (vd cạnh hàng tab). */
  actionsOnMobileOnly?: boolean;
};

/** Đầu trang quản trị: tiêu đề + dòng phụ bên trái, nút bên phải (mọi khổ cùng một hàng). */
export function PageHeader({ title, description, descriptionBelow = false, primaryAction, actions = [], moreLabel = "", aside, actionsOnMobileOnly = false }: PageHeaderProps) {
  return (
    <header className="flex animate-fade-in items-center justify-between gap-3">
      {/* Gọn: tiêu đề và dòng phụ cùng một dòng (hết chỗ thì dòng phụ xuống dưới); nút luôn cùng hàng tiêu đề */}
      <div className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-3 gap-y-0.5">
        <h1 className="text-lg font-bold sm:text-xl">{title}</h1>
        {description ? (
          <div className={cn("text-xs text-muted sm:text-ui", descriptionBelow && "basis-full")}>{description}</div>
        ) : null}
      </div>
      {aside ?? (
        <PageActions
          primaryAction={primaryAction}
          actions={actions}
          moreLabel={moreLabel}
          className={actionsOnMobileOnly ? "sm:hidden" : undefined}
        />
      )}
    </header>
  );
}

type PageActionsProps = Pick<PageHeaderProps, "primaryAction" | "actions" | "moreLabel"> & { className?: string };

/** Khối nút của đầu trang (dùng riêng được, vd đặt cạnh hàng tab). */
export function PageActions({ primaryAction, actions = [], moreLabel = "", className }: PageActionsProps) {
  return (
    <div className={cn("flex shrink-0 items-center gap-2 sm:gap-3", className)}>
      {/* Từ sm: nút phụ hiện thẳng, trước nút chính */}
      {actions.length > 0 ? (
        <div className="hidden gap-3 sm:flex">
          {actions.map((a) => (
            // Mục "plain": chữ trơn, chỉ có hiệu ứng khi rê. Còn lại sm–lg chỉ icon (chữ sr-only + title), từ lg đủ chữ
            a.plain ? (
              <Button key={a.label} variant="ghost" onClick={a.onClick}>
                {a.label}
              </Button>
            ) : (
            <Button key={a.label} variant="secondary" onClick={a.onClick} title={a.label}>
              {a.icon}
              <span className="sr-only lg:not-sr-only">{a.label}</span>
            </Button>
            )
          ))}
        </div>
      ) : null}
      {primaryAction ? (
        // Nút chính luôn có chữ (icon trơn người dùng không đoán được); điện thoại chữ ngắn, tên đầy đủ qua aria-label
        <Button onClick={primaryAction.onClick} aria-label={primaryAction.label}>
          {primaryAction.icon}
          {primaryAction.shortLabel ? (
            <>
              <span className="sm:hidden">{primaryAction.shortLabel}</span>
              <span className="hidden sm:inline">{primaryAction.label}</span>
            </>
          ) : (
            primaryAction.label
          )}
        </Button>
      ) : null}
      {/* Điện thoại: nút phụ gom vào ⋮, đặt SAU nút chính ngay trong DOM (thứ tự Tab trùng thứ tự nhìn) */}
      {actions.length > 0 ? <ActionMenu label={moreLabel} items={actions} outline className={cn(`
        sm:hidden
      `)} /> : null}
    </div>
  );
}
