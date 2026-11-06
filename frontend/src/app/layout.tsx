import type { Metadata, Viewport } from "next";
import { Be_Vietnam_Pro } from "next/font/google";
import { getBranding } from "@/lib/api/server";
import { site, siteDescription } from "@/lib/site";
import "./globals.css";

const font = Be_Vietnam_Pro({
  variable: "--font-be-vietnam",
  subsets: ["vietnamese", "latin"],
  weight: ["400", "500", "600", "700", "800"],
});

export async function generateMetadata(): Promise<Metadata> {
  const { name, favicon_url: favicon } = await getBranding();
  return {
    metadataBase: new URL(site.url),
    title: { default: `${name} – Đặt sân cầu lông online`, template: `%s | ${name}` },
    description: siteDescription(name),
    applicationName: name,
    // Không đặt alternates.canonical ở đây: trang con sẽ kế thừa và trỏ canonical về trang chủ.
    // Mỗi trang public tự khai báo canonical của mình.
    openGraph: {
      type: "website",
      locale: "vi_VN",
      siteName: name,
      url: "/",
    },
    formatDetection: { telephone: false },
    // Có logo ⇒ favicon theo logo (URL có ?v= đổi theo ảnh); chưa có ⇒ app/favicon.ico mặc định
    ...(favicon ? { icons: { icon: favicon } } : {}),
  };
}

export const viewport: Viewport = {
  viewportFit: "cover",
  themeColor: "#1a7354",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="vi" className={`${font.variable} h-full antialiased 3xl:text-[112.5%] 4xl:text-[125%]`}>
      <body className="flex min-h-full flex-col font-sans">{children}</body>
    </html>
  );
}
