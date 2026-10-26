import { Suspense } from "react";
import { openingText, WithPublicPrices } from "@/components/public-prices";
import { fullAddress, phoneHref, site } from "@/lib/site";

export function SiteFooter() {
  return (
    <footer className="mt-16 border-t border-border bg-surface">
      <div className="mx-auto grid max-w-6xl gap-6 px-4 py-10 text-sm sm:grid-cols-3">
        <div>
          <p className="font-semibold">{site.name}</p>
          <address className="mt-2 not-italic text-muted">{fullAddress}</address>
        </div>
        <div>
          <p className="font-semibold">Liên hệ</p>
          <p className="mt-2 text-muted">
            Hotline: <a href={phoneHref}>{site.phone}</a>
            <br />
            Email: <a href={`mailto:${site.email}`}>{site.email}</a>
          </p>
        </div>
        {/* Giờ mở cửa lấy từ booking engine lúc chạy (một nguồn sự thật); chưa có dữ liệu → ẩn cả mục, không in số tĩnh. */}
        <Suspense fallback={null}>
          <WithPublicPrices>
            {(data) =>
              openingText(data) ? (
                <div>
                  <p className="font-semibold">Giờ mở cửa</p>
                  <p className="mt-2 text-muted">Hằng ngày {openingText(data)}</p>
                </div>
              ) : null
            }
          </WithPublicPrices>
        </Suspense>
      </div>
    </footer>
  );
}
