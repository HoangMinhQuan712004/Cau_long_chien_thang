import type { Metadata } from "next";
import { ComingSoon } from "@/components/member-area/coming-soon";

export const metadata: Metadata = { title: "Lịch sử thanh toán" };

export default function Page() {
  return <ComingSoon title="Lịch sử thanh toán" />;
}
