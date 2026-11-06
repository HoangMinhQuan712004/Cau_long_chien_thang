import { Avatar } from "@/components/member-area/avatar";
import type { RecordBreakItem } from "@/components/records/requests";
import { cn } from "@/lib/cn";
import { formatDayMonth, formatTime, vnDate, weekdayIndex } from "@/lib/format";
import { videoYoutubeId, youtubeThumb } from "@/lib/video";

// Thẻ kỷ lục + dòng thời gian "Các lần phá kỷ lục" (T-048 AC2, AC4, AC5, AC7). Dữ liệu và quyền riêng tư do server quyết định (T-030):
// trường null thì ẩn cả mục, không để ô trống.

const WEEKDAY = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];
const when = (iso: string) => `${WEEKDAY[weekdayIndex(vnDate(iso))]} ${formatDayMonth(vnDate(iso))} · ${formatTime(iso)}`;
const heldText = (days: number) => (days < 1 ? "Dưới 1 ngày" : `${days} ngày`);

const PinIcon = () => (
  <svg viewBox="0 0 24 24" className="size-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
    <path d="M12 21s7-6.2 7-11.5a7 7 0 0 0-14 0C5 14.8 12 21 12 21z" />
    <circle cx="12" cy="9.5" r="2.5" />
  </svg>
);
const ClockIcon = () => (
  <svg viewBox="0 0 24 24" className="size-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3 2" />
  </svg>
);

/** Thẻ "Kỷ lục hiện tại" / "Kỷ lục ngày dd/mm" bên cạnh trình phát. */
export function RecordCard({ item }: { item: RecordBreakItem }) {
  const label = item.is_current ? "Kỷ lục hiện tại" : `Kỷ lục ngày ${formatDayMonth(item.label_date)}`;
  const delta = item.is_baseline || item.delta_kmh === null ? "Mốc đầu" : `+${item.delta_kmh} km/h${item.previous_kmh !== null ? ` · phá kỷ lục ${item.previous_kmh} km/h` : ""}`;
  return (
    <section aria-label={label} className="flex h-full flex-col overflow-hidden rounded-2xl bg-surface shadow-card ring-2 ring-cta/80">
      <div className="bg-accent-soft px-5 pt-4 pb-5 text-center">
        <p className="inline-flex items-center rounded-full bg-cta px-4 py-1 text-xs font-bold tracking-wide text-cta-fg uppercase">{label}</p>
        <p className="mt-2 flex items-baseline justify-center gap-1.5 text-accent-fg">
          <span className="text-6xl leading-none font-extrabold tabular-nums sm:text-7xl">{item.speed_kmh}</span>
          <span className="text-lg font-semibold">km/h</span>
        </p>
        <p className="mx-auto mt-2 w-fit max-w-full rounded-full border border-cta bg-surface px-3 py-1 text-xs font-semibold text-accent-fg">{delta}</p>
      </div>

      <div className="flex flex-1 flex-col gap-3 p-4 sm:p-5">
        <div className="flex items-center gap-3">
          <Avatar url={item.avatar_url} name={item.display_name} size={52} />
          <div className="min-w-0">
            <p className="flex flex-wrap items-center gap-x-2 text-lg leading-tight font-bold">
              <span className="break-words">{item.display_name}</span>
              {item.is_me ? <span className="rounded-full bg-primary-softer px-2 py-0.5 text-xs font-semibold text-primary">Bạn</span> : null}
            </p>
            {item.nickname ? <p className="text-sm font-semibold text-accent-fg">“{item.nickname}”</p> : null}
            <p className="text-xs text-muted">{item.tier ? `Hội viên · Trình độ ${item.tier}` : "Hội viên"}</p>
          </div>
        </div>

        {item.racket ? (
          <div className="rounded-xl border border-cta bg-accent-soft/50 px-4 py-3">
            <p className="text-xs font-bold tracking-wide text-accent-fg uppercase">Vợt phá kỷ lục</p>
            <p className="mt-0.5 font-bold break-words">{item.racket}</p>
          </div>
        ) : null}

        <div className="mt-auto grid grid-cols-2 gap-2 text-sm">
          {item.resource_name ? (
            <div className="min-w-0 rounded-xl bg-primary-softer px-3 py-2">
              <p className="flex items-center gap-1.5 text-xs text-muted">
                <PinIcon /> Sân
              </p>
              <p className="font-semibold break-words">{item.resource_name}</p>
            </div>
          ) : null}
          <div className={cn("min-w-0 rounded-xl bg-primary-softer px-3 py-2", item.resource_name ? "" : "col-span-2")}>
            <p className="flex items-center gap-1.5 text-xs text-muted">
              <ClockIcon /> Thời điểm
            </p>
            <p className="font-semibold tabular-nums">{when(item.measured_at)}</p>
          </div>
        </div>
      </div>
    </section>
  );
}

/** Ảnh dòng: YouTube dùng ảnh server trả; mp4 / webm dùng khung mặc định (không tải video của từng dòng); không có video thì ghi rõ. */
function RowThumb({ item }: { item: RecordBreakItem }) {
  const v = item.video;
  const yt = v && v.kind === "youtube" ? videoYoutubeId(v) : null;
  return (
    <span aria-hidden className="relative grid aspect-video w-24 shrink-0 place-items-center overflow-hidden rounded-lg bg-appbar text-surface sm:w-36">
      {yt ? (
        // eslint-disable-next-line @next/next/no-img-element -- ảnh xem trước của YouTube, không qua tối ưu ảnh của Next
        <img src={v?.thumbnail_url?.startsWith("https://i.ytimg.com/") ? v.thumbnail_url : youtubeThumb(yt)} alt="" loading="lazy" referrerPolicy="no-referrer" className="absolute inset-0 size-full object-cover" />
      ) : null}
      {v ? (
        <span className="relative grid size-8 place-items-center rounded-full bg-cta text-cta-fg shadow-card sm:size-9">
          <svg viewBox="0 0 24 24" className="size-4 translate-x-px" fill="currentColor">
            <path d="M8 5.5v13l11-6.5z" />
          </svg>
        </span>
      ) : (
        <span className="relative px-1 text-center text-[11px] leading-tight text-surface/80">Chưa có video</span>
      )}
    </span>
  );
}

function Row({ item, selected, onSelect }: { item: RecordBreakItem; selected: boolean; onSelect: () => void }) {
  const day = vnDate(item.measured_at);
  const meta = [item.racket, item.resource_name, formatTime(item.measured_at)].filter(Boolean).join(" · ");
  return (
    <li className="relative">
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected ? "true" : undefined}
        className={cn("flex min-h-11 w-full items-center gap-3 rounded-xl border px-2 py-2 text-left focus-ring sm:gap-4 sm:px-3", selected ? "border-cta bg-accent-soft" : "border-transparent hover:bg-primary-softer")}
      >
        <span className="w-11 shrink-0 text-center tabular-nums sm:w-14">
          <b className="block text-sm sm:text-base">{formatDayMonth(day)}</b>
          <span className="block text-xs text-muted">{day.slice(0, 4)}</span>
        </span>
        <RowThumb item={item} />
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <b className="text-lg tabular-nums">{item.speed_kmh} km/h</b>
            {item.delta_kmh !== null ? <span className="rounded-full bg-primary-softer px-2 py-0.5 text-xs font-semibold text-primary tabular-nums">+{item.delta_kmh} km/h</span> : null}
            {item.is_current ? <span className="rounded-full bg-cta px-2 py-0.5 text-xs font-bold text-cta-fg">Đang giữ kỷ lục</span> : null}
          </span>
          <span className="block truncate text-sm font-semibold">
            {item.display_name}
            {item.nickname ? <span className="font-normal text-accent-fg"> “{item.nickname}”</span> : null}
            {item.is_me ? " (Bạn)" : ""}
          </span>
          {meta ? <span className="block truncate text-xs text-muted">{meta}</span> : null}
          <span className="mt-0.5 block text-xs text-muted sm:hidden">
            Giữ kỷ lục <b className="text-foreground">{heldText(item.held_days)}</b>
          </span>
        </span>
        <span className="hidden shrink-0 text-right text-xs text-muted sm:block">
          Giữ kỷ lục
          <b className={cn("block text-sm", item.is_current ? "text-accent-fg" : "text-foreground")}>{heldText(item.held_days)}</b>
        </span>
        <svg aria-hidden viewBox="0 0 24 24" className="hidden size-5 shrink-0 text-subtle sm:block" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="m9 6 6 6-6 6" />
        </svg>
      </button>
    </li>
  );
}

/** Mốc đầu: dòng gọn ở cuối, chỉ có ở "Mọi thời gian"; vẫn bấm được để xem thẻ. */
function BaselineRow({ item, selected, onSelect }: { item: RecordBreakItem; selected: boolean; onSelect: () => void }) {
  const day = vnDate(item.measured_at);
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected ? "true" : undefined}
        className={cn("flex min-h-11 w-full items-center gap-3 rounded-xl border px-2 py-2 text-left focus-ring sm:gap-4 sm:px-3", selected ? "border-cta bg-accent-soft" : "border-transparent hover:bg-primary-softer")}
      >
        <span className="w-11 shrink-0 text-center tabular-nums sm:w-14">
          <b className="block text-sm sm:text-base">{formatDayMonth(day)}</b>
          <span className="block text-xs text-muted">{day.slice(0, 4)}</span>
        </span>
        <span className="min-w-0 flex-1">
          <b className="block">Mốc đầu {item.speed_kmh} km/h</b>
          <span className="block text-xs text-muted">Hệ thống bắt đầu ghi nhận kỷ lục từ ngày này</span>
        </span>
      </button>
    </li>
  );
}

export function BreakTimeline({ items, selectedId, onSelect }: { items: RecordBreakItem[]; selectedId: number | undefined; onSelect: (item: RecordBreakItem) => void }) {
  return (
    <ol className="mt-3 space-y-1">
      {items.map((r) =>
        r.is_baseline ? <BaselineRow key={r.id} item={r} selected={r.id === selectedId} onSelect={() => onSelect(r)} /> : <Row key={r.id} item={r} selected={r.id === selectedId} onSelect={() => onSelect(r)} />,
      )}
    </ol>
  );
}
