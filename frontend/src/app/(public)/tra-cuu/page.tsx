import type { Metadata } from "next";
import { LookupScreen } from "@/components/web-booking/lookup-screen";
import { getBranding } from "@/lib/api/server";

export async function generateMetadata(): Promise<Metadata> {
  const { name } = await getBranding();
  return {
    title: "Tra cứu booking",
    description: `Tra cứu booking tại ${name} bằng mã booking và số điện thoại đã dùng khi đặt sân.`,
    alternates: { canonical: "/tra-cuu" },
  };
}

export default async function LookupPage() {
  const { phone } = await getBranding();
  return <LookupScreen hotline={phone} />;
}
