import { Card } from "@/components/ui/card";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton, SkeletonTable } from "@/components/ui/skeleton";

/** Khung tải màn Hội viên: tiêu đề hiện ngay (khi đã có chữ), tóm tắt/nút/bộ lọc/bảng là khối giữ chỗ. */
export function MemberSkeleton({ title, label }: { title?: string; label?: string }) {
  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title={title ?? <Skeleton className="h-7 w-32" />}
        description={<Skeleton className="h-4 w-56 max-w-full" />}
        aside={
          // Điện thoại: nút ở đầu trang; từ sm nút nằm cùng hàng tab
          <div className="flex shrink-0 gap-2 sm:hidden">
            <Skeleton className="h-8 w-16 rounded-lg sm:h-8.5 sm:w-36" />
            {/* Bọc div để ẩn/hiện: Skeleton đã có sẵn class block */}
            <div className="hidden sm:block">
              <Skeleton className="h-9.5 w-36 rounded-lg" />
            </div>
            <Skeleton className="h-8 w-16 rounded-lg sm:h-8.5 sm:w-36" />
          </div>
        }
      />
      {/* Hàng tab Loại */}
      <div className="flex items-center gap-6 border-b px-4 pb-2">
        <Skeleton className="h-5 w-20" />
        <Skeleton className="h-5 w-24" />
        <Skeleton className="h-5 w-28" />
        {/* Từ sm: 3 nút canh phải cùng hàng tab */}
        <div className="ml-auto hidden gap-3 sm:flex">
          <Skeleton className="h-8.5 w-24 rounded-lg" />
          <Skeleton className="h-8.5 w-10 rounded-lg lg:w-32" />
          <Skeleton className="h-8.5 w-36 rounded-lg" />
        </div>
      </div>
      {/* Điện thoại: không khung ngoài (thẻ hội viên dùng hết bề ngang) */}
      <Card bareOnMobile className="flex flex-col gap-3 sm:gap-4 sm:p-5">
        {/* Giống FilterBar: ô tìm; hàng ô chọn (điện thoại vuốt ngang); từ xl chung hàng */}
        <div className="flex flex-col gap-3 xl:flex-row">
          <Skeleton className="h-8 rounded-lg sm:h-9.5 xl:flex-1" />
          <div className="flex gap-2 overflow-hidden">
            <Skeleton className="h-8 w-40 shrink-0 rounded-lg sm:h-9.5 sm:w-52" />
            <Skeleton className="h-8 w-32 shrink-0 rounded-lg sm:h-9.5 sm:w-52" />
            <Skeleton className="h-8 w-28 shrink-0 rounded-lg sm:h-9.5 sm:w-56" />
          </div>
        </div>
        <SkeletonTable rows={8} cols={6} label={label} />
      </Card>
    </div>
  );
}
