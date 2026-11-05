import { JsonLd } from "@/components/json-ld";
import type { PublicPrices } from "@/lib/api/server";
import { formatVnd } from "@/lib/format";
import { site } from "@/lib/site";

/** JSON-LD SportsActivityLocation của sân (tên, địa chỉ, giờ mở cửa, khoảng giá) – đặt trên trang chính /dat-san. */
export function LocalBusinessJsonLd({ data }: { data: PublicPrices | null }) {
  const prices = data?.prices.map((p) => p.price_per_hour) ?? [];
  const open = data?.opening_hours.earliest_open?.slice(0, 5);
  const close = data?.opening_hours.latest_close?.slice(0, 5);
  return (
    <JsonLd
      data={{
        "@context": "https://schema.org",
        "@type": "SportsActivityLocation",
        name: site.name,
        description: site.description,
        url: site.url,
        telephone: site.phone,
        address: {
          "@type": "PostalAddress",
          streetAddress: `${site.address.street}, ${site.address.ward}`,
          addressLocality: site.address.district,
          addressRegion: site.address.city,
          addressCountry: site.address.country,
        },
        geo: { "@type": "GeoCoordinates", latitude: site.geo.lat, longitude: site.geo.lng },
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
