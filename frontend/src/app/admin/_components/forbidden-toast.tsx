"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { toast } from "@/lib/feedback";
import { FORBIDDEN_KEY as KEY, FORBIDDEN_VALUE as VALUE } from "./forbidden";

/** Có `?ly-do=khong-quyen` ⇒ báo lỗi một lần (E-001) rồi bỏ tham số khỏi URL (F5 không báo lại). */
export function ForbiddenToast({ message }: { message: string }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const isForbidden = searchParams.get(KEY) === VALUE;

  useEffect(() => {
    if (!isForbidden) return;
    toast(message, undefined, "error");
    const rest = new URLSearchParams(searchParams);
    rest.delete(KEY);
    const qs = rest.toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }, [isForbidden, message, pathname, router, searchParams]);

  return null;
}
