"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { BreakTimeline } from "@/components/member-area/record-breaks";
import { RecordCard } from "@/components/member-area/record-card";
import { RecordPlayer } from "@/components/records/record-player";
import { getMemberVideos, getRecordBreaks, type MemberRecordVideo, type RecordBreakItem, type VideoPeriod } from "@/components/records/requests";
import { errorText } from "@/lib/api/write";
import { cn } from "@/lib/cn";
import { type LiveRecord, useLiveRecords } from "@/lib/live-records";
import { LiveRecordTakeover } from "./live-record-takeover";
import { PageBanner } from "./page-banner";
import { AllVideos } from "./record-videos";

// /hoi-vien/video-ky-luc (T-048, thay AC4 của T-046). 25/11 (người dùng): số đo chỉ đến từ camera AI – bỏ "Gửi cú đập" / "Của tôi";
// kỷ lục mới từ máy đo ⇒ màn "Kỷ lục mới" toàn màn hình, video về thì phát video.
// vùng banner = trình phát + thẻ kỷ lục của lần đang chọn, bên dưới là 2 tab: "Phá kỷ lục" (dòng thời gian các lần phá kỷ lục chung)
// và "Tất cả video" (mọi cú đập có video trong kỳ, người dùng 27/11).
// Tên / biệt danh / trình độ / vợt theo quy tắc ẩn danh T-030 (server quyết định).

const PERIODS: { key: VideoPeriod; label: string }[] = [
  { key: "week", label: "Tuần" },
  { key: "month", label: "Tháng" },
  { key: "year", label: "Năm" },
  { key: "all", label: "Mọi thời gian" },
];

type Tab = "breaks" | "videos";
const chip = (on: boolean) => cn("h-11 shrink-0 rounded-full border px-5 text-sm font-semibold whitespace-nowrap focus-ring sm:h-10", on ? "border-primary-hover bg-primary-hover text-surface" : "border-border-strong bg-surface hover:bg-primary-softer");
const seg = (on: boolean) => cn("h-11 shrink-0 rounded-full px-4 text-sm font-semibold whitespace-nowrap focus-ring-inverse sm:h-9", on ? "bg-surface text-primary-hover" : "text-surface hover:bg-surface/15");

export function VideoScreen() {
  const [period, setPeriod] = useState<VideoPeriod>("all");
  const [items, setItems] = useState<RecordBreakItem[] | null>(null);
  const [selectedId, setSelectedId] = useState<number | undefined>();
  const [error, setError] = useState("");
  const [cheer, setCheer] = useState<LiveRecord | null>(null);
  const [tab, setTab] = useState<Tab>("breaks");
  const [videos, setVideos] = useState<MemberRecordVideo[] | null>(null);
  const [videosError, setVideosError] = useState("");
  const videoSeq = useRef(0);
  const closeCheer = useCallback(() => setCheer(null), []);
  const seq = useRef(0);
  const stage = useRef<HTMLDivElement>(null);

  const load = useCallback(async (p: VideoPeriod, quiet = false) => {
    const n = ++seq.current;
    if (!quiet) {
      setItems(null);
      setSelectedId(undefined); // đổi kỳ thì chọn lại lần mới nhất của kỳ đó (AC8)
    }
    setError("");
    const res = await getRecordBreaks(p);
    if (n !== seq.current) return; // chỉ nhận kết quả của lần gọi mới nhất
    if (res.ok) setItems(res.data.items);
    else setError(errorText(res.error));
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải lại khi đổi kỳ
    void load(period);
  }, [load, period]);

  // Tab "Tất cả video": tải khi mở tab / đổi kỳ (chỉ nhận kết quả của lần gọi mới nhất)
  const loadVideos = useCallback(async (p: VideoPeriod, quiet = false) => {
    const n = ++videoSeq.current;
    if (!quiet) setVideos(null);
    setVideosError("");
    const res = await getMemberVideos(p);
    if (n !== videoSeq.current) return;
    if (res.ok) setVideos(res.data.items);
    else setVideosError(errorText(res.error));
  }, []);
  useEffect(() => {
    if (tab !== "videos") return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải khi mở tab hoặc đổi kỳ
    void loadVideos(period);
  }, [loadVideos, period, tab]);

  // Máy đo: kỷ lục mới ⇒ màn toàn màn hình + tải lại; video cắt ghép về ⇒ màn đó phát video, danh sách tải lại (giữ lựa chọn đang xem)
  useLiveRecords((e) => {
    if (e.event === "record.new") setCheer(e.record);
    else setCheer((c) => (c && c.record_id === e.record.record_id ? e.record : c));
    void load(period, true);
    if (tab === "videos") void loadVideos(period, true);
  });

  const selected = items?.find((r) => r.id === selectedId) ?? items?.[0];
  const breaks = items?.filter((r) => !r.is_baseline).length ?? 0; // dòng phụ không tính mốc đầu

  function pick(r: RecordBreakItem) {
    setSelectedId(r.id); // không tự phát: trình phát dựng lại theo `key`, video cũ dừng
    if (window.matchMedia("(max-width: 1023px)").matches) {
      const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      stage.current?.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" });
    }
  }

  return (
    <>
      <PageBanner
        title="Video & kỷ lục"
        subtitle="Cú cầu nhanh nhất cụm sân · video chỉ đăng khi có kỷ lục mới"
        aside={
          <div className="flex max-w-full gap-1 overflow-x-auto rounded-full bg-surface/10 p-1" role="group" aria-label="Kỳ kỷ lục">
            {PERIODS.map((p) => (
              <button key={p.key} type="button" aria-pressed={period === p.key} onClick={() => setPeriod(p.key)} className={seg(period === p.key)}>
                {p.label}
              </button>
            ))}
          </div>
        }
      >
        <div ref={stage} className="relative mx-auto max-w-6xl scroll-mt-20 px-4 pb-6 sm:pb-8">
          {error ? (
            <div role="alert" className="space-y-2 rounded-2xl bg-surface/10 px-6 py-10 text-center text-sm">
              <p>{error}</p>
              <button type="button" onClick={() => void load(period)} className="h-11 rounded-lg border border-surface/60 px-4 font-semibold hover:bg-surface/15 focus-ring-inverse">
                Thử lại
              </button>
            </div>
          ) : items === null ? (
            <p className="py-16 text-center text-surface/80" aria-busy>
              Đang tải…
            </p>
          ) : !selected ? (
            <div className="grid place-items-center rounded-2xl bg-surface/10 px-6 py-14 text-center">
              <h2 className="text-lg font-bold">{period === "all" ? "Chưa có kỷ lục nào" : "Chưa có lần phá kỷ lục trong kỳ này"}</h2>
              <p className="mt-1 max-w-sm text-sm text-surface/80">{period === "all" ? "Kỷ lục sẽ hiện ở đây khi cụm sân ghi nhận cú đập đầu tiên." : "Thử chọn kỳ dài hơn."}</p>
            </div>
          ) : (
            <div className="grid gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
              <RecordPlayer key={selected.id} video={selected.video} speed={selected.speed_kmh} name={selected.display_name} />
              <RecordCard item={selected} />
            </div>
          )}
        </div>
      </PageBanner>

      <div className="mx-auto max-w-6xl px-4 py-6 sm:py-8">
        <section className="rounded-2xl bg-surface p-4 shadow-card sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-bold">{tab === "breaks" ? "Các lần phá kỷ lục" : "Tất cả video"}</h2>
              <p className="text-sm text-muted">
                {tab === "breaks"
                  ? items
                    ? `${breaks} lần · mới nhất ở trên · bấm một dòng để xem video`
                    : ""
                  : videos
                    ? `${videos.length} video · mọi cú đập có video trong kỳ · bấm để xem`
                    : ""}
              </p>
            </div>
            <div className="flex gap-2" role="tablist" aria-label="Danh sách">
              <button type="button" role="tab" aria-selected={tab === "breaks"} onClick={() => setTab("breaks")} className={chip(tab === "breaks")}>
                Phá kỷ lục
              </button>
              <button type="button" role="tab" aria-selected={tab === "videos"} onClick={() => setTab("videos")} className={chip(tab === "videos")}>
                Tất cả video
              </button>
            </div>
          </div>

          {tab === "breaks" ? (
            items && items.length > 0 ? <BreakTimeline items={items} selectedId={selected?.id} onSelect={pick} /> : null
          ) : (
            <AllVideos items={videos} error={videosError} onRetry={() => void loadVideos(period)} />
          )}
        </section>
      </div>

      {cheer ? <LiveRecordTakeover key={cheer.record_id} record={cheer} onClose={closeCheer} /> : null}
    </>
  );
}
