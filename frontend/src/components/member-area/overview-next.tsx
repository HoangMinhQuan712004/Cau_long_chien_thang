import Link from "next/link";
import { Avatar } from "@/components/member-area/avatar";
import { hourRange } from "@/components/play-rooms/utils";
import type { components } from "@/lib/api/schema";
import { cn } from "@/lib/cn";
import { formatDayMonth } from "@/lib/format";
import { ctaCls } from "./overview-parts";

// Khối nổi của Tổng quan: "Tiếp theo" (lịch chơi gần nhất) – nền xanh nhạt; chưa có lịch ⇒ gợi ý Đặt sân.

type Upcoming = components["schemas"]["UpcomingItem"];

const WEEKDAY = ["CN", "T2", "T3", "T4", "T5", "T6", "T7"];
/** "Hôm nay" hoặc "T5, 13/11" (thứ viết tắt + ngày/tháng). `playDate` là ngày VN dạng YYYY-MM-DD. */
const dayLabel = (playDate: string, today: string) =>
  playDate === today ? "Hôm nay" : `${WEEKDAY[new Date(`${playDate}T00:00:00Z`).getUTCDay()]}, ${formatDayMonth(playDate)}`;

/** Cụm avatar + "x/8": điện thoại cùng hàng, từ sm (giữa sân) số nằm dưới avatar. */
function Members({ item }: { item: Upcoming }) {
  // API chỉ gửi tối đa 4 avatar xem trước ⇒ số người còn lại hiện "+n"
  const more = (item.count ?? 0) - item.members_preview.length;
  return (
    <div className="flex w-fit items-center gap-2 sm:flex-col sm:gap-1">
      <div className="flex -space-x-1.5" aria-hidden>
        {item.members_preview.map((m, i) => (
          <Avatar key={`${m.display_name}-${i}`} url={m.avatar_url} name={m.display_name} size={26} className="ring-2 ring-primary-softer" />
        ))}
        {more > 0 ? (
          <span className="relative grid size-[1.625rem] place-items-center rounded-full bg-primary text-[0.625rem] font-bold text-surface ring-2 ring-primary-softer">+{more}</span>
        ) : null}
      </div>
      <span className="rounded-full bg-primary-softer px-1.5 text-sm font-semibold tabular-nums" aria-label={`${item.count} trên ${item.capacity} thành viên`}>
        {item.count}/{item.capacity}
      </span>
    </div>
  );
}

/** Sân nhỏ vẽ bằng nét; từ sm cụm avatar "x/8" nằm đè giữa sân (điện thoại ẩn sân, cụm avatar ở cột trái). */
function MiniCourt({ item }: { item: Upcoming }) {
  return (
    <div className="relative hidden min-w-0 flex-1 items-center justify-center sm:flex">
      <svg viewBox="0 0 160 70" preserveAspectRatio="none" className="absolute inset-x-0 top-1/2 h-16 w-full -translate-y-1/2 text-primary/40" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden>
        <rect x="1" y="1" width="158" height="68" />
        <path d="M80 1v68M1 35h158M30 1v68M130 1v68" />
      </svg>
      {item.capacity !== null ? (
        <div className="relative">
          <Members item={item} />
        </div>
      ) : null}
    </div>
  );
}

/** Viền đứt đoạn xanh "chạy" quanh thẻ khi đang diễn ra; tắt chuyển động nếu máy bật giảm chuyển động. */
function RunningBorder() {
  return (
    <svg aria-hidden className="pointer-events-none absolute inset-0 size-full overflow-visible">
      <rect
        x="1"
        y="1"
        rx="15"
        style={{ width: "calc(100% - 2px)", height: "calc(100% - 2px)" }}
        fill="none"
        strokeWidth="1.5"
        strokeDasharray="3 3"
        className="stroke-primary motion-safe:animate-dash-run"
      />
    </svg>
  );
}

function EnterLink({ id, className }: { id: number; className?: string }) {
  return (
    <Link href={`/hoi-vien/phong/${id}`} className={cn("inline-flex h-8 shrink-0 items-center justify-center rounded-md bg-primary px-3 text-xs font-semibold text-surface hover:bg-primary-hover focus-ring", className)}>
      Vào phòng
    </Link>
  );
}

export function NextCard({ item, today }: { item: Upcoming; today: string }) {
  const ongoing = item.phase === "ongoing";
  return (
    <article className="relative flex flex-col gap-4 rounded-2xl bg-primary-softer p-4 sm:flex-row sm:p-6">
      {ongoing ? <RunningBorder /> : null}
      <div className="min-w-0 sm:shrink-0">
        {/* Đang chơi ⇒ nhãn "ĐANG DIỄN RA" thay cho "TIẾP THEO" (không hiện cả hai) */}
        {ongoing ? (
          <p className="flex items-center gap-1.5 text-xs font-bold tracking-wider text-accent-fg">
            <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-accent" />
            ĐANG DIỄN RA
          </p>
        ) : (
          <p className="text-xs font-bold tracking-wider text-primary">TIẾP THEO</p>
        )}
        <p className="mt-1 text-2xl leading-tight font-bold whitespace-nowrap xl:text-3xl">
          {dayLabel(item.play_date, today)} · <span className="tabular-nums">{hourRange(item.start_at, item.end_at)}</span>
        </p>
        <p className="mt-1 text-sm text-muted">
          {item.resource_name} · {item.resource_type_name} · Host: <b className="font-semibold text-foreground">{item.role === "host" ? "bạn" : item.host_name}</b>
        </p>
        {/* Điện thoại: avatar + số người bên trái, nút Vào phòng bên phải trên cùng một hàng */}
        <div className={cn("mt-3 flex items-center justify-between gap-3", item.capacity !== null && "sm:hidden")}>
          {item.capacity !== null ? (
            <Members item={item} />
          ) : (
            <p className="text-sm text-muted">Phòng đang được tạo</p>
          )}
          {item.room_id !== null ? <EnterLink id={item.room_id} className="sm:hidden" /> : null}
        </div>
      </div>
      <div className="hidden items-stretch gap-4 sm:flex sm:min-w-0 sm:flex-1">
        <MiniCourt item={item} />
        {/* Cột hành động canh giữa theo sân, nút gọn theo chữ (bỏ "Còn n phút" 12/11) */}
        <div className="flex shrink-0 flex-col justify-center">
          {item.room_id !== null ? <EnterLink id={item.room_id} /> : null}
        </div>
      </div>
    </article>
  );
}

/** Chưa có lịch chơi sắp tới: một dòng chữ + nút Đặt sân, canh giữa (như mẫu người dùng 12/11). */
export function NoNext() {
  return (
    <div className="rounded-2xl bg-primary-softer px-4 py-6 text-center ring-1 ring-primary/10">
      <p className="text-muted">Bạn chưa có lịch chơi sắp tới</p>
      <Link href="/hoi-vien/dat-san" className={cn(ctaCls, "mt-4")}>
        Đặt sân
      </Link>
    </div>
  );
}
