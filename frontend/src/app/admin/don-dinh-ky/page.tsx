import { redirect } from "next/navigation";

// Route cũ của T-039: màn Đơn định kỳ nay là "Đơn đặt sân" (T-041).
export default function OldRecurringOrdersPage() {
  redirect("/admin/don-dat-san");
}
