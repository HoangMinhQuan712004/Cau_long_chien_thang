import type { Metadata } from "next";
import { PlayHistoryScreen } from "@/components/member-area/play-history-screen";

export const metadata: Metadata = { title: "Lịch sử chơi" };

export default function Page() {
  return <PlayHistoryScreen />;
}
