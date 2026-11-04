import type { MetadataRoute } from "next";
import { getPosts } from "@/lib/api/server";
import { site } from "@/lib/site";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const posts = await getPosts(100);
  const staticRoutes = [
    // "/" chuyển vĩnh viễn tới /dat-san (next.config.ts): chỉ khai báo trang đích, là trang chính
    { path: "/dat-san", priority: 1, changeFrequency: "daily" as const },
    { path: "/tra-cuu", priority: 0.6, changeFrequency: "monthly" as const },
    { path: "/bang-gia", priority: 0.8, changeFrequency: "monthly" as const },
    { path: "/tin-tuc", priority: 0.6, changeFrequency: "weekly" as const },
  ];
  return [
    ...staticRoutes.map((r) => ({
      url: `${site.url}${r.path}`,
      changeFrequency: r.changeFrequency,
      priority: r.priority,
    })),
    ...posts.map((p) => ({
      url: `${site.url}/tin-tuc/${p.slug}`,
      lastModified: p.updated_at,
      changeFrequency: "monthly" as const,
      priority: 0.5,
    })),
  ];
}
