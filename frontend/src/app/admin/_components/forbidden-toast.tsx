"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { toast } from "@/lib/feedback";
import { FORBIDDEN_KEY as KEY } from "./forbidden";

/**
 * Có `?ly-do=<giá trị>` khớp `messages` ⇒ báo lỗi một lần (E-001) rồi bỏ tham số khỏi URL (F5 không báo lại).
 * Mỗi giá trị một câu (vd `khong-quyen` chung, `khong-quyen-bao-cao` riêng màn Báo cáo).
 */
export function ForbiddenToast({ messages }: { messages: Record<string, string> }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const reason = searchParams.get(KEY);
  const message = reason !== null && Object.hasOwn(messages, reason) ? messages[reason] : null;

  useEffect(() => {
    if (!message) return;
    toast(message, undefined, "error");
    const rest = new URLSearchParams(searchParams);
    rest.delete(KEY);
    const qs = rest.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }, [message, pathname, router, searchParams]);

  return null;
}
