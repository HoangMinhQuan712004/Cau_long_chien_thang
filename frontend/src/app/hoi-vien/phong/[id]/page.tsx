import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { RoomScreen } from "@/components/play-rooms/room-screen";

export const metadata: Metadata = { title: "Phòng chơi" };

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  return (
    <Suspense fallback={<p className="py-20 text-center text-muted">Đang tải…</p>}>
      <Room params={params} />
    </Suspense>
  );
}

async function Room({ params }: { params: Promise<{ id: string }> }) {
  const id = Number((await params).id);
  if (!Number.isInteger(id) || id <= 0) notFound();
  return <RoomScreen id={id} />;
}
