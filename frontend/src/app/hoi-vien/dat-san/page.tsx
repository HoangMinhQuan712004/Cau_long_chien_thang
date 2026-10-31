import type { Metadata } from "next";
import { ComingSoon } from "@/components/member-area/coming-soon";

export const metadata: Metadata = { title: "Đặt sân" };

export default function Page() {
  return <ComingSoon title="Đặt sân" />;
}
