import { JsonLd } from "@/components/json-ld";
import type { PublicPrices, SiteBranding } from "@/lib/api/server";
import { formatVnd } from "@/lib/format";
import { site, siteDescription } from "@/lib/site";

/** JSON-LD SportsActivityLocation của sân (tên, địa chỉ, giờ mở cửa, khoảng giá) – đặt trên trang chính /dat-san. */
export function LocalBusinessJsonLd({ data, info }: { data: PublicPrices | null; info: SiteBranding }) {
  const prices = data?.prices.map((p) => p.price_per_hour) ?? [];
  const open = data?.opening_hours.earliest_open?.slice(0, 5);
  const close = data?.opening_hours.latest_close?.slice(0, 5);
  return (
    <JsonLd
      data={{
        "@context": "https://schema.org",
        "@type": "SportsActivityLocation",
        name: info.name,
        description: siteDescription(info.name),
        url: site.url,
        telephone: info.phone,
        address: { "@type": "PostalAddress", streetAddress: info.address, addressCountry: "VN" },
        // Chỉ khi Admin đã nhập tọa độ: không in tọa độ cố định, sẽ sai khi đổi địa chỉ
        ...(info.lat != null && info.lng != null && { geo: { "@type": "GeoCoordinates", latitude: info.lat, longitude: info.lng } }),
        ...(open &&
          close && {
            openingHoursSpecification: {
              "@type": "OpeningHoursSpecification",
              dayOfWeek: ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
              opens: open,
              closes: close,
            },
          }),
        ...(prices.length && {
          priceRange: `${formatVnd(Math.min(...prices))} – ${formatVnd(Math.max(...prices))}/giờ`,
        }),
      }}
    />
  );
}
