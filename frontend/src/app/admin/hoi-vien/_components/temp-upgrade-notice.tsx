import { Button } from "@/components/ui/button";
import { InfoIcon } from "@/components/ui/icons";
import type { Dictionary } from "@/i18n/dictionaries";
import type { TempMatch } from "@/lib/api/members";
import { cn } from "@/lib/cn";

type Props = {
  temp: TempMatch;
  isPending: boolean;
  onUpgrade: () => void;
  onDismiss: () => void;
  t: Dictionary["members"]["form"];
};

/** Form Thêm gặp SĐT của hồ sơ tạm (E-MEM-1): đề nghị nâng hồ sơ đó thành hội viên, giữ lịch sử đặt sân. */
export function TempUpgradeNotice({ temp, isPending, onUpgrade, onDismiss, t }: Props) {
  const bookings = temp.bookings > 0 ? t.upgradeBookings.replace("{n}", String(temp.bookings)) : "";
  return (
    <div role="status" className={cn(`
      flex flex-col gap-3 rounded-lg border border-primary/30 bg-primary-softer p-3 text-sm
    `)}>
      <p className="flex gap-2">
        <InfoIcon size={18} className="mt-0.5 shrink-0 text-primary" />
        <span>
          {t.upgradeNote
            .replace("{name}", temp.fullName)
            .replace("{bookings}", bookings)
            .replace("{code}", temp.nextCode)}
        </span>
      </p>
      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onDismiss} disabled={isPending}>
          {t.cancel}
        </Button>
        <Button type="button" loading={isPending} onClick={onUpgrade}>
          {isPending ? t.upgrading : t.upgrade}
        </Button>
      </div>
    </div>
  );
}
