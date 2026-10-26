import type { Metadata } from "next";
import Link from "next/link";
import { JsonLd } from "@/components/json-ld";
import { PriceTable } from "@/components/price-table";
import { getPublicPrices } from "@/lib/api/server";
import { formatVnd } from "@/lib/format";
import { fullAddress, phoneHref, site } from "@/lib/site";

export const metadata: Metadata = {
  alternates: { canonical: "/" },
};

export default async function HomePage() {
  const data = await getPublicPrices();
  const prices = data?.prices.map((p) => p.price_per_hour) ?? [];
  const opens = data?.opening_hours.earliest_open?.slice(0, 5) ?? site.openingHours.open;
  const closes = data?.opening_hours.latest_close?.slice(0, 5) ?? site.openingHours.close;

  return (
    <>
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
          openingHoursSpecification: {
            "@type": "OpeningHoursSpecification",
            dayOfWeek: [
              "Monday",
              "Tuesday",
              "Wednesday",
              "Thursday",
              "Friday",
              "Saturday",
              "Sunday",
            ],
            opens,
            closes,
          },
          ...(prices.length && {
            priceRange: `${formatVnd(Math.min(...prices))} – ${formatVnd(Math.max(...prices))}/giờ`,
          }),
        }}
      />

      <section className="grid items-center gap-8 py-8 md:grid-cols-2">
        <div>
          <h1 className="text-3xl font-bold leading-tight sm:text-4xl">
            {site.name}
            <span className="block text-primary">Giá rõ ràng, đặt sân tại quầy</span>
          </h1>
          <p className="mt-4 text-muted">{site.description}</p>
          <p className="mt-2 text-sm text-muted">📍 {fullAddress}</p>
          <div className="mt-6 flex flex-wrap gap-3">
            <a href={phoneHref} className="rounded-md bg-primary px-5 py-3 font-medium text-primary-fg">
              Gọi {site.phone}
            </a>
            <Link href="/bang-gia" className="rounded-md border border-border px-5 py-3">
              Bảng giá
            </Link>
          </div>
          <p className="mt-3 text-sm text-muted">
            Đặt sân tại quầy hoặc gọi hotline. Giờ mở cửa {opens} – {closes}. Đặt sân trực tuyến sẽ sớm có.
          </p>
        </div>
        <ul className="grid grid-cols-2 gap-3">
          {data?.resource_types.map((t) => (
            <li key={t.code} className="rounded-lg border border-border bg-surface p-4">
              <p className="font-semibold">{t.name}</p>
              <p className="text-sm text-muted">{t.resource_count} sân</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="py-8">
        <h2 className="mb-4 text-2xl font-semibold">Bảng giá thuê sân</h2>
        <PriceTable data={data} />
      </section>
    </>
  );
}
