"use client";

import { useCallback, useEffect, useState } from "react";
import { roomsApi } from "@/components/play-rooms/requests";
import type { RoomCard } from "@/components/play-rooms/types";
import { Button } from "@/components/ui/button";
import { usePolling } from "@/hooks/use-polling";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { errorText } from "@/lib/api/write";
import { toast } from "@/lib/feedback";
import { formatLongDate, vnMinutes } from "@/lib/format";
import { UpcomingEvents } from "./overview-events";
import { NextCard, NoNext } from "./overview-next";
import { OverviewBanner, type StatItem } from "./overview-banner";
import { RankPanel } from "./overview-rank";
import { RecordCards } from "./overview-records";
import { OpenRooms } from "./overview-rooms";

// /hoi-vien – Tổng quan v2 (T-036): banner + 3 thẻ số, Tiếp theo, Phòng đang trống, Sự kiện, Hạng của tôi + Top 3,
// Kỷ lục mới (mỗi khối một file overview-*.tsx).
// Một lần gọi GET /member-area/overview (kiểu sinh từ schema.d.ts). Khối không có dữ liệu thì ẩn hoặc hiện trạng thái trống.

type Overview = components["schemas"]["Overview"];

const monthNo = (ym: string | undefined, today: string) => Number((ym ?? today).slice(5, 7));

/** 05–11 sáng, 11–18 chiều, còn lại tối (giờ Việt Nam). */
function greetingOf(nowMs: number): string {
  const hour = vnMinutes(new Date(nowMs).toISOString()) / 60;
  return hour >= 5 && hour < 11 ? "sáng" : hour >= 11 && hour < 18 ? "chiều" : "tối";
}

const CARD = "rounded-2xl bg-surface p-4 shadow-card sm:p-6";

export function OverviewScreen() {
  const [data, setData] = useState<Overview | null>(null);
  const [failed, setFailed] = useState(false);
  // Mốc lúc tải gần nhất: dùng cho lời chào (không đọc đồng hồ khi render)
  const [nowMs, setNowMs] = useState(0);
  const [busyId, setBusyId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const ov = await api.GET("/api/v1/member-area/overview");
      if (ov.response.status === 401) {
        window.location.replace(`/dang-nhap?next=${encodeURIComponent("/hoi-vien")}&ly-do=het-han`);
        return;
      }
      if (ov.data) {
        setData(ov.data);
        setNowMs(Date.now());
        setFailed(false);
      } else setFailed(true);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- tải lần đầu khi vào trang
    void load();
  }, [load]);
  usePolling(() => void load(), 15000);

  /** "Xin vào" ở khối Phòng đang trống: đúng API xin vào của T-017 (kèm version phòng). */
  async function requestJoin(room: RoomCard) {
    if (busyId !== null) return;
    setBusyId(room.id);
    try {
      const res = await roomsApi.requestJoin(room.id, room.version);
      if (!res.ok) toast(errorText(res.error), undefined, "error");
      else toast("Đã gửi yêu cầu vào phòng", `${room.resource_name} · Host sẽ duyệt`);
    } finally {
      setBusyId(null);
    }
    await load();
  }

  const next = data?.upcoming[0];
  const month = data ? monthNo(data.month, data.today) : 0;

  return (
    <>
      <OverviewBanner
        title={
          data ? (
            <>
              {/* Tên cùng màu nút Đặt sân (vàng cta), như app bar điện thoại */}
              Chào buổi {greetingOf(nowMs)}, <span className="text-cta">{data.greeting_name}</span>
            </>
          ) : (
            "Tổng quan"
          )
        }
        subtitle={data ? `${formatLongDate(data.today)} · Bạn có ${data.today_count} lịch chơi hôm nay` : "Đang tải…"}
        month={month}
        stats={statItems(data)}
      />

      {/* Chỉ bỏ khung lồng khung: mỗi đơn vị nội dung (lịch + phòng trống, hạng, từng sự kiện, từng kỷ lục) một thẻ */}
      <div className="mx-auto max-w-6xl px-4 py-6 sm:py-8">
        {failed && !data ? (
          <div role="alert" className="rounded-card bg-surface p-8 text-center shadow-card">
            <p className="font-semibold">Không tải được tổng quan. Vui lòng thử lại.</p>
            <Button className="mt-4" onClick={() => void load()}>
              Thử lại
            </Button>
          </div>
        ) : !data ? (
          <p className="py-10 text-center text-muted" aria-busy>
            Đang tải…
          </p>
        ) : (
          <div className="space-y-8 sm:space-y-10">
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_22rem] lg:items-start lg:gap-6">
              {/* Một thẻ: "Tiếp theo" + Phòng đang trống (thiết kế prototype, người dùng 04/11) */}
              <section className={CARD} aria-labelledby="up-title">
                <h2 id="up-title" className="sr-only">
                  Lịch chơi tiếp theo
                </h2>
                {next ? <NextCard item={next} today={data.today} /> : <NoNext />}
                <div className="mt-6">
                  <OpenRooms rooms={data.open_rooms} busyId={busyId} onJoin={(r) => void requestJoin(r)} />
                </div>
              </section>
              <div className="lg:sticky lg:top-24">
                <RankPanel ranking={data.ranking} month={month} />
              </div>
            </div>
            <UpcomingEvents events={data.upcoming_events} />
            <RecordCards records={data.recent_records} />
          </div>
        )}
      </div>
    </>
  );
}

// ------------------------------------------------------------------ 3 số tháng của banner

function statItems(data: Overview | null): StatItem[] {
  if (!data) return [];
  const st = data.month_stats;
  const rec = data.month_record_kmh;
  return [
    { href: "/hoi-vien/lich-su-choi", label: "Buổi chơi", value: st ? String(st.sessions) : "—", unit: "buổi" },
    { href: "/hoi-vien/lich-su-choi", label: "Trận thắng", value: st ? String(st.wins) : "—", unit: st ? `/ ${st.matches} trận` : "" },
    {
      href: "/hoi-vien/bang-xep-hang",
      label: "Kỷ lục cá nhân",
      value: rec != null ? String(rec) : "—",
      unit: rec != null ? "km/h" : "",
      sub: rec == null && data.record_kmh != null ? `Kỷ lục mọi thời gian: ${data.record_kmh} km/h` : undefined,
    },
  ];
}
