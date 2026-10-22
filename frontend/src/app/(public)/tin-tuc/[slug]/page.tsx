import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { JsonLd } from "@/components/json-ld";
import { getPost } from "@/lib/api/server";
import { formatDate } from "@/lib/format";
import { site } from "@/lib/site";

export async function generateMetadata({
  params,
}: PageProps<"/tin-tuc/[slug]">): Promise<Metadata> {
  const { slug } = await params;
  const post = await getPost(slug);
  if (!post) return { title: "Không tìm thấy bài viết", robots: { index: false } };
  const description = post.meta_description ?? post.excerpt ?? undefined;
  return {
    title: post.meta_title ?? post.title,
    description,
    alternates: { canonical: `/tin-tuc/${post.slug}` },
    openGraph: {
      type: "article",
      title: post.title,
      description,
      publishedTime: post.published_at ?? undefined,
      images: post.cover_url ? [post.cover_url] : undefined,
    },
  };
}

export default function PostPage({ params }: PageProps<"/tin-tuc/[slug]">) {
  // params là dữ liệu runtime -> đặt sau Suspense (Cache Components)
  return (
    <Suspense fallback={<p className="text-muted">Đang tải bài viết…</p>}>
      <PostContent params={params} />
    </Suspense>
  );
}

async function PostContent({ params }: Pick<PageProps<"/tin-tuc/[slug]">, "params">) {
  const { slug } = await params;
  const post = await getPost(slug);
  if (!post) notFound();

  return (
    <article className="mx-auto max-w-3xl">
      <JsonLd
        data={{
          "@context": "https://schema.org",
          "@type": "Article",
          headline: post.title,
          description: post.excerpt,
          datePublished: post.published_at,
          dateModified: post.updated_at,
          image: post.cover_url ?? undefined,
          publisher: { "@type": "Organization", name: site.name, url: site.url },
          mainEntityOfPage: `${site.url}/tin-tuc/${post.slug}`,
        }}
      />
      <h1 className="text-3xl font-bold">{post.title}</h1>
      {post.published_at && (
        <p className="mt-2 text-sm text-muted">
          <time dateTime={post.published_at}>{formatDate(post.published_at)}</time>
        </p>
      )}
      {/* Nội dung do admin soạn (HTML). Nếu cho người ngoài viết, cần sanitize ở backend. */}
      <div
        className="mt-6 space-y-4 leading-relaxed"
        dangerouslySetInnerHTML={{ __html: post.content }}
      />
    </article>
  );
}
