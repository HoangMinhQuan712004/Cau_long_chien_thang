import { BOOKING_STATUS_LABEL } from "@/lib/format";

const STYLE: Record<string, string> = {
  pending: "bg-accent/20 text-foreground",
  confirmed: "bg-primary/15 text-primary",
  completed: "bg-busy text-muted",
  cancelled: "bg-danger/10 text-danger",
  expired: "bg-busy text-muted",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${STYLE[status] ?? ""}`}>
      {BOOKING_STATUS_LABEL[status] ?? status}
    </span>
  );
}
