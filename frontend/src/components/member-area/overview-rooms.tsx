import type { RoomCard } from "@/components/play-rooms/types";
import { hourRange, joinBlockText, tierRangeText } from "@/components/play-rooms/utils";
import { Button } from "@/components/ui/button";
import { SectionHead } from "./overview-parts";

// "Phòng đang trống" của Tổng quan: danh sách dòng không khung, tách bằng đường kẻ mảnh.

export function OpenRooms({ rooms, busyId, onJoin }: { rooms: RoomCard[]; busyId: number | null; onJoin: (r: RoomCard) => void }) {
  return (
    <section aria-labelledby="open-title">
      <SectionHead id="open-title" title="Phòng đang trống" href="/hoi-vien/danh-sach-san" link="Xem phòng chơi" />
      {rooms.length === 0 ? (
        <p className="py-6 text-sm text-muted">Hôm nay chưa có phòng còn chỗ</p>
      ) : (
        <ul className="mt-2 divide-y divide-border">
          {rooms.map((r) => {
            const range = tierRangeText(r.tier_range);
            const reason = joinBlockText(r.my_join_block);
            return (
              <li key={r.id} className="flex flex-wrap items-center gap-x-3 gap-y-2 py-3.5">
                {/* Trái: sân · giờ, host, hạng; phải: số người + nút – điện thoại cũng giữ một hàng */}
                <span className="min-w-0 flex-1">
                  <span className="block font-semibold">
                    {r.resource_name} · <span className="tabular-nums">{hourRange(r.start_at, r.end_at)}</span>
                  </span>
                  <span className="block truncate text-sm text-muted">Host: {r.host.display_name}</span>
                  {range ? <span className="mt-1 inline-block rounded-full bg-primary-softer px-2.5 py-0.5 text-xs font-semibold text-primary">{range}</span> : null}
                </span>
                <span className="flex shrink-0 items-center gap-3">
                  <span className="text-sm font-semibold tabular-nums" aria-label={`${r.member_count} trên 8 thành viên`}>
                    {r.member_count}/8
                  </span>
                  {r.my_join_pending ? (
                    <Button variant="secondary" className="h-10 sm:h-10" disabled>
                      Đã xin vào
                    </Button>
                  ) : (
                    <Button variant="secondary" className="h-10 sm:h-10" onClick={() => onJoin(r)} loading={busyId === r.id} disabled={Boolean(r.my_join_block)} title={reason ?? undefined}>
                      Xin vào
                    </Button>
                  )}
                </span>
                {reason && !r.my_join_pending ? (
                  <p role="note" className="basis-full text-xs text-muted">
                    {reason}
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
