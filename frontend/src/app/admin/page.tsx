import { redirect } from "next/navigation";

// Màn Đặt sân (booking engine) là trang vào mặc định của khu quản trị; tài khoản quầy vào thẳng đây.
export default function AdminIndexPage() {
  redirect("/admin/dat-san");
}
