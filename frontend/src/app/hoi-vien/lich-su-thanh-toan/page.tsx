import type { Metadata } from "next";
import { PaymentsScreen } from "@/components/member-area/payments-screen";

export const metadata: Metadata = { title: "Lịch sử thanh toán" };

export default function Page() {
  return <PaymentsScreen />;
}
