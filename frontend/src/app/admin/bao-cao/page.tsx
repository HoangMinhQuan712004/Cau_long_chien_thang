import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Suspense } from "react";
import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { getDictionary } from "@/i18n/dictionaries";
import { cn } from "@/lib/cn";
import { adminMenuOrder, adminPerms, authedApi, type ReportOverview } from "@/lib/api/server";
import { can, FORBIDDEN_REPORT_PARAM, firstAllowedHref } from "../_components/forbidden";
import { ChartSkeleton } from "./_components/chart-parts";
import { presetPeriod } from "./_components/report-period";
import { ReportScreen } from "./_components/report-screen";

export async function generateMetadata(): Promise<Metadata> {
  return { title: (await getDictionary()).report.metaTitle };
}

export default function ReportPage() {
  return (
    <Suspense fallback={<ReportSkeleton />}>
      <ReportLoader />
    </Suspense>
  );
}


// Theo quyền reports.view (BR-001): thiếu quyền ⇒ về mục được phép + báo E-001; backend vẫn kiểm quyền mỗi lần lấy số liệu
async function ReportLoader() {
  const [t, perms, order] = await Promise.all([getDictionary(), adminPerms(), adminMenuOrder()]);
  // Thiếu quyền ⇒ về mục đầu tiên được phép + báo E-001
  const FORBIDDEN = `${firstAllowedHref(perms, order)}?${FORBIDDEN_REPORT_PARAM}`;
  if (!can(perms, "reports.view")) redirect(FORBIDDEN);

  // Mở màn luôn là kỳ Tuần (BR-002); tải sẵn ở server để vào là có số
  const week = presetPeriod("week");
  const api = await authedApi();
  const res = await api
    .GET("/api/v1/admin/reports/overview", { params: { query: { from: week.from, to: week.to } } })
    .catch(() => null);
  if (res?.response.status === 403) redirect(FORBIDDEN);
  const initial: ReportOverview | null = res?.data ?? null;

  // key theo dữ liệu server: Next 16 giữ trang đã rời trong <Activity> nên state cũ (useState(initial)) không tự lấy props mới khi quay lại bằng menu
  return <ReportScreen key={initial?.computed_at ?? "none"} initial={initial} today={week.to} t={t.report} />;
}

// Khung chờ đúng hình màn: đầu trang, bộ lọc, 3 thẻ, 2 biểu đồ, heatmap (không nhảy bố cục)
function ReportSkeleton() {
  return (
    // Cùng khung với màn thật: rộng tối đa 7xl (màn 1920 không kéo dãn quá rộng)
    <div className="flex w-full flex-col gap-3 sm:gap-4 lg:gap-5">
      <PageHeader
        title={<Skeleton className="h-7 w-52" />}
        description={<Skeleton className="h-4 w-80 max-w-full" />}
        descriptionBelow
        aside={<Skeleton className="h-8 w-24 rounded-lg sm:h-8.5" />}
      />
      <div className="flex flex-col gap-2">
        <Skeleton className="h-8 w-full max-w-160 rounded-lg sm:h-9.5" />
        <Skeleton className="h-4 w-80 max-w-full" />
      </div>
      {/* Cùng lưới thẻ chỉ số: điện thoại thẻ đầu rộng hết hàng, 2 thẻ sau 2 cột */}
      <div className="grid grid-cols-2 gap-2.5 sm:gap-3 md:grid-cols-3 lg:gap-4">
        {[0, 1, 2].map((i) => (
          <Card
            key={i}
            className={cn(
              "flex flex-col gap-2 px-3 py-2.5 sm:px-4 sm:py-3.5 lg:px-4.5 lg:py-4",
              i === 0 && "col-span-2 md:col-span-1",
            )}
          >
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-6 w-32 sm:h-7 sm:w-40 xl:h-8" />
            <Skeleton className="h-4 w-full max-w-52" />
          </Card>
        ))}
      </div>
      <div className="grid gap-3 lg:gap-4 xl:grid-cols-2">
        {[0, 1].map((i) => (
          <Card key={i} className="flex flex-col gap-3 px-4 py-3.5 lg:px-4.5 lg:py-4">
            <Skeleton className="h-5 w-40" />
            <ChartSkeleton />
          </Card>
        ))}
      </div>
    </div>
  );
}
