import { cn } from "@/lib/cn";

type EmptyStateProps = {
  /** Icon 24px (vd InboxIcon, SearchXIcon), đặt trong vòng tròn. */
  icon?: React.ReactNode;
  title: React.ReactNode;
  description?: React.ReactNode;
  /** Hành động gợi ý (nút / link). */
  action?: React.ReactNode;
};

/** Trạng thái không có dữ liệu: icon, câu chính, gợi ý và một hành động, căn giữa. */
export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex animate-fade-in flex-col items-center gap-3 px-4 py-6 text-center">
      {icon ? (
        <div aria-hidden className={cn(`
          grid size-12 place-items-center rounded-full bg-background text-muted
        `)}>
          {icon}
        </div>
      ) : null}
      <div className="flex flex-col gap-1">
        <p className="text-base font-semibold text-foreground">{title}</p>
        {description ? <p className="max-w-prose text-sm text-muted">{description}</p> : null}
      </div>
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}
