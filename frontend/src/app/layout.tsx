import type { Metadata, Viewport } from "next";
import { Be_Vietnam_Pro } from "next/font/google";
import { site } from "@/lib/site";
import "./globals.css";

const font = Be_Vietnam_Pro({
  variable: "--font-be-vietnam",
  subsets: ["vietnamese", "latin"],
  weight: ["400", "500", "600", "700", "800"],
});

export const metadata: Metadata = {
  metadataBase: new URL(site.url),
  title: { default: `${site.name} – Đặt sân cầu lông online`, template: `%s | ${site.name}` },
  description: site.description,
  applicationName: site.name,
  // Không đặt alternates.canonical ở đây: trang con sẽ kế thừa và trỏ canonical về trang chủ.
  // Mỗi trang public tự khai báo canonical của mình.
  openGraph: {
    type: "website",
    locale: "vi_VN",
    siteName: site.name,
    url: "/",
  },
  formatDetection: { telephone: false },
};

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
