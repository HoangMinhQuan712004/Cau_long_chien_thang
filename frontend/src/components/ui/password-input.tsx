"use client";

import { useState } from "react";
import { cn } from "@/lib/cn";
import { EyeIcon, EyeOffIcon } from "./icons";
import { Input } from "./input";

type PasswordInputProps = Omit<React.ComponentProps<typeof Input>, "type" | "endSlot"> & {
  /** Nhãn nút cho trình đọc màn hình, lấy từ từ điển (vd "Hiện mật khẩu" / "Ẩn mật khẩu"). */
  showLabel: string;
  hideLabel: string;
};

/** Ô mật khẩu có nút hiện/ẩn; chỉ đổi cách hiển thị, không gửi gì lên máy chủ. */
export function PasswordInput({ showLabel, hideLabel, ...props }: PasswordInputProps) {
  const [isVisible, setIsVisible] = useState(false);

  return (
    <Input
      {...props}
      type={isVisible ? "text" : "password"}
      endSlot={
        <button
          type="button"
          onClick={() => setIsVisible((v) => !v)}
          disabled={props.disabled}
          aria-pressed={isVisible}
          aria-label={isVisible ? hideLabel : showLabel}
          // Nhìn 32px như prototype, vùng chạm nới ra 44px cho điện thoại
          className={cn(`
            relative grid size-8 place-items-center rounded-lg focus-ring transition-colors
            after:absolute after:-inset-1.5
            enabled:hover:bg-background
            disabled:cursor-not-allowed
          `)}
        >
          {isVisible ? <EyeOffIcon /> : <EyeIcon />}
        </button>
      }
    />
  );
}
