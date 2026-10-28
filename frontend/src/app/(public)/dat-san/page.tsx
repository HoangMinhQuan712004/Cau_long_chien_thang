import type { Metadata } from "next";
import { Suspense } from "react";
import { BookingBoard } from "@/components/booking/booking-board";
import { getDictionary } from "@/i18n/dictionaries";
import { getVenueConfig } from "@/lib/api/server";
import { site } from "@/lib/site";

export async function generateMetadata(): Promise<Metadata> {
  const t = (await getDictionary()).booking;
  return {
    title: t.metaTitle,
    description: t.metaDescription.replace("{name}", site.name),
    alternates: { canonical: "/dat-san" },
  };
}

// Trang đặt sân; chữ theo ngôn ngữ trong cookie nên tiêu đề và lịch nằm trong Suspense
export default function BookingPage() {
  return (
    <div className="space-y-6">
      <Suspense fallback={<div aria-hidden className="h-9 w-40 animate-pulse rounded-lg bg-border" />}>
        <Title />
      </Suspense>
      <Suspense fallback={<div aria-hidden className="h-96 animate-pulse rounded-lg bg-border" />}>
        <Board />
      </Suspense>
    </div>
  );
}

async function Title() {
  return <h1 className="text-3xl font-bold">{(await getDictionary()).booking.title}</h1>;
}

async function Board() {
  const [config, dictionary] = await Promise.all([getVenueConfig(), getDictionary()]);
  return (
    <BookingBoard
      maxAdvanceDays={config?.max_advance_days ?? 30}
      t={dictionary.booking}
      phoneVerifyTexts={dictionary.phoneVerify}
    />
  );
}
