import { redirect } from "next/navigation";

// Logo nay nằm trong mục Thông tin web; giữ URL cũ để link đã có vẫn chạy
export default function SiteLogoPage() {
  redirect("/admin/cai-dat/thong-tin-web");
}
