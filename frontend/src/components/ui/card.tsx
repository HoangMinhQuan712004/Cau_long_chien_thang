import { cn } from "@/lib/cn";
type CardProps = React.HTMLAttributes<HTMLDivElement>;

export function Card({ className = "", ...props }: CardProps) {
  return (
    <div
      className={cn("rounded-card border bg-surface shadow-card", className)}
      {...props}
    />
  );
}
