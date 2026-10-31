import type { Metadata } from "next";
import { ComingSoon } from "@/components/member-area/coming-soon";

export const metadata: Metadata = { title: "Video & kỷ lục" };

export default function Page() {
  return <ComingSoon title="Video & kỷ lục" />;
}
