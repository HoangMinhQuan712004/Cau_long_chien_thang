// Video kỷ lục gắn thủ công (T-046): chỉ nhận link https của YouTube hoặc file .mp4 / .webm.
// Kiểm ở FE chỉ để báo sớm và xem thử; server (E-REC-1) mới là nơi quyết định.

export type RecordVideo = { kind: "youtube" | "file"; url: string; embed_url?: string | null };

const YT_ID = /^[\w-]{11}$/;
const YT_HOSTS = new Set(["youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"]);

/** Mã video YouTube (11 ký tự) từ link watch / youtu.be / shorts / embed; null nếu không phải YouTube hợp lệ. */
export function youtubeId(raw: string): string | null {
  let u: URL;
  try {
    u = new URL(raw.trim());
  } catch {
    return null;
  }
  if (u.protocol !== "https:" || !YT_HOSTS.has(u.hostname.toLowerCase())) return null;
  const parts = u.pathname.split("/").filter(Boolean);
  const id = u.hostname.toLowerCase().endsWith("youtu.be") ? parts[0] : parts[0] === "watch" ? u.searchParams.get("v") : ["shorts", "embed", "live"].includes(parts[0] ?? "") ? parts[1] : null;
  return id && YT_ID.test(id) ? id : null;
}

/** Phân loại link người dùng dán; null = không hợp lệ (chỉ https, YouTube hoặc .mp4 / .webm). */
export function parseVideoUrl(raw: string): RecordVideo | null {
  const url = raw.trim();
  if (!url) return null;
  if (youtubeId(url)) return { kind: "youtube", url };
  try {
    const u = new URL(url);
    if (u.protocol === "https:" && /\.(mp4|webm)$/i.test(u.pathname)) return { kind: "file", url };
  } catch {
    /* link sai định dạng */
  }
  return null;
}

/** Mã YouTube của một video đã lưu: ưu tiên `url`, rồi `embed_url` của server. FE tự dựng link nhúng, không tin nguyên văn `embed_url`. */
export const videoYoutubeId = (v: RecordVideo): string | null => youtubeId(v.url) ?? (v.embed_url ? youtubeId(v.embed_url.replace("youtube-nocookie.com", "youtube.com")) : null);

export const youtubeEmbed = (id: string) => `https://www.youtube-nocookie.com/embed/${id}?autoplay=1&rel=0`;
export const youtubeThumb = (id: string) => `https://i.ytimg.com/vi/${id}/hqdefault.jpg`;

export const VIDEO_LINK_HINT = "Chỉ nhận link YouTube hoặc file .mp4 / .webm (https).";
