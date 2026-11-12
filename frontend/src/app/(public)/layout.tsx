import { FeedbackHost } from "@/components/feedback/feedback-host";
import { SiteFooter } from "@/components/site-footer";
import { SiteHeader } from "@/components/site-header";

export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return (
    // data-fluid-text: chữ gốc co giãn theo màn như khu hội viên; overflow-x-clip: banner tràn hết bề ngang (vd /dat-san) không gây cuộn ngang; không tạo khung cuộn nên sticky vẫn chạy
    <div data-fluid-text className="flex flex-1 flex-col overflow-x-clip">
      <SiteHeader />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">{children}</main>
      <SiteFooter />
      <FeedbackHost />
    </div>
  );
}
