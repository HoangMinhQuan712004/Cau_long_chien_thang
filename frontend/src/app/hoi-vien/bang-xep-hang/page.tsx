import type { Metadata } from "next";
import { RankingScreen } from "@/components/member-area/ranking-screen";

export const metadata: Metadata = { title: "Bảng xếp hạng" };

export default function Page() {
  return <RankingScreen />;
}
