import { EventCard, type EventCardData } from "@/components/play-rooms/event-card";
import { SectionHead } from "./overview-parts";

// "Sự kiện sắp tới" của Tổng quan (T-045): không thẻ bao ngoài, mỗi sự kiện là thẻ gốc (EventCard – đủ trường như tab
// Sự kiện). Điện thoại vuốt ngang, từ sm lưới 2 cột, từ lg 3 cột.

/** Tối đa 3 sự kiện trong 14 ngày tới; không có thì ẩn cả khối. */
export function UpcomingEvents({ events }: { events: EventCardData[] | undefined }) {
  if (!events || events.length === 0) return null;
  return (
    <section aria-labelledby="ev-title">
      <SectionHead id="ev-title" title="Sự kiện sắp tới" href="/hoi-vien/danh-sach-san?loc=su-kien" link="Xem tất cả" />
      <ul className="-mx-4 mt-3 flex snap-x snap-mandatory gap-3 overflow-x-auto scroll-px-4 px-4 pb-1 scrollbar-none sm:mx-0 sm:grid sm:grid-cols-2 sm:gap-4 sm:overflow-visible sm:px-0 lg:grid-cols-3">
        {events.map((e) => (
          <li key={e.code} className="w-[85%] shrink-0 snap-start sm:w-auto">
            <EventCard e={e} />
          </li>
        ))}
      </ul>
    </section>
  );
}
