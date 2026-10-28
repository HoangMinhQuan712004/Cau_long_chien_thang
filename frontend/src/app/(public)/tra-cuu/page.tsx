import type { Metadata } from "next";
import { LookupScreen } from "@/components/web-booking/lookup-screen";
import { site } from "@/lib/site";

export const metadata: Metadata = {
  title: "Tra cứu booking",
  description: `Tra cứu booking tại ${site.name} bằng mã booking và số điện thoại đã dùng khi đặt sân.`,
  alternates: { canonical: "/tra-cuu" },
};

export default function LookupPage() {
  return <LookupScreen hotline={site.phone} />;
}
