import type { Metadata } from "next";
import { ComingSoon } from "@/components/member-area/coming-soon";

export const metadata: Metadata = { title: "Danh sách sân" };

export default function Page() {
  return <ComingSoon title="Danh sách sân" />;
}
