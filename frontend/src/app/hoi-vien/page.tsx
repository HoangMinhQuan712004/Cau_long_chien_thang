import type { Metadata } from "next";
import { ComingSoon } from "@/components/member-area/coming-soon";

export const metadata: Metadata = { title: "Tổng quan" };

export default function Page() {
  return <ComingSoon title="Tổng quan" />;
}
