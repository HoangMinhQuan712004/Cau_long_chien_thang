import "server-only";
import { cookies } from "next/headers";
import { cache } from "react";
import type vi from "./messages/vi.json";

// Thêm ngôn ngữ: tạo messages/<mã>.json cùng cấu trúc vi.json rồi khai báo ở đây
const DICTIONARIES = {
  vi: () => import("./messages/vi.json").then((m) => m.default),
};

type Locale = keyof typeof DICTIONARIES;
export type Dictionary = typeof vi;

const DEFAULT_LOCALE: Locale = "vi";
/** Ngôn ngữ chọn lưu ở cookie, URL giữ nguyên (khu quản trị + webview). */
const LOCALE_COOKIE = "lang";

const hasLocale = (value: string | undefined): value is Locale =>
  value !== undefined && value in DICTIONARIES;

async function getLocale(): Promise<Locale> {
  const value = (await cookies()).get(LOCALE_COOKIE)?.value;
  return hasLocale(value) ? value : DEFAULT_LOCALE;
}

/** Một lần mỗi request dù metadata và trang cùng gọi. */
export const getDictionary = cache(async (): Promise<Dictionary> => DICTIONARIES[await getLocale()]());
