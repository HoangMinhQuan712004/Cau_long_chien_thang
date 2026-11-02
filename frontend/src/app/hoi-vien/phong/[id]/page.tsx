import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { RoomScreen } from "@/components/play-rooms/room-screen";

export const metadata: Metadata = { title: "Phòng chơi" };

export default function Page({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ tab?: string }> }) {
  return (
    <Suspense fallback={<p className="py-20 text-center text-muted">Đang tải…</p>}>
      <Room params={params} searchParams={searchParams} />
    </Suspense>
  );
}

async function Room({ params, searchParams }: { params: Promise<{ id: string }>; searchParams: Promise<{ tab?: string }> }) {
  const id = Number((await params).id);
  if (!Number.isInteger(id) || id <= 0) notFound();
  // ?tab=history: mở thẳng tab Lịch sử trận đấu (từ màn Lịch sử chơi, T-029 AC3)
  const tab = (await searchParams).tab === "history" ? "history" : "play";
  return <RoomScreen id={id} initialTab={tab} />;
}
