import type { Metadata } from "next";
import { OverviewScreen } from "@/components/member-area/overview-screen";

export const metadata: Metadata = { title: "Tổng quan" };

export default function Page() {
  return <OverviewScreen />;
}
