import type { Metadata } from "next";
import Link from "next/link";
import { getBranding, getPosts } from "@/lib/api/server";
import { formatDate } from "@/lib/format";

export async function generateMetadata(): Promise<Metadata> {
  const { name } = await getBranding();
  return {
    title: "Tin tức & kinh nghiệm chơi cầu lông",
    description: `Tin tức, khuyến mãi và kinh nghiệm chơi cầu lông từ ${name}.`,
    alternates: { canonical: "/tin-tuc" },
  };
}

export default async function NewsPage() {
  const posts = await getPosts();
  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Tin tức</h1>
      {!posts.length && <p className="text-muted">Chưa có bài viết.</p>}
      <ul className="grid gap-4 sm:grid-cols-2">
        {posts.map((p) => (
          <li key={p.id} className="rounded-lg border border-border bg-surface p-5">
            <Link href={`/tin-tuc/${p.slug}`} className="text-lg font-semibold hover:text-primary">
              {p.title}
            </Link>
            {p.published_at && (
              <p className="text-sm text-muted">
                <time dateTime={p.published_at}>{formatDate(p.published_at)}</time>
              </p>
            )}
            {p.excerpt && <p className="mt-2 text-muted">{p.excerpt}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}
