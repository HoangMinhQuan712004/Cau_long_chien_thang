"use client";

import Script from "next/script";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { GoogleLogoIcon } from "@/components/ui/icons";

const GIS_SRC = "https://accounts.google.com/gsi/client";
const CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID ?? "";
const MAX_BUTTON_WIDTH = 400;

type GoogleId = {
  initialize: (config: {
    client_id: string;
    callback: (response: { credential: string }) => void;
    ux_mode: "popup";
    context: "signin";
  }) => void;
  renderButton: (parent: HTMLElement, options: Record<string, string | number>) => void;
};

declare global {
  interface Window {
    google?: { accounts: { id: GoogleId } };
  }
}

// Webview trong app (Google chặn đăng nhập ở đây): Android "; wv)", iOS thiếu "Safari", app mạng xã hội
function isEmbeddedBrowser(userAgent: string): boolean {
  if (/; wv\)/.test(userAgent)) return true;
  if (/iPhone|iPad|iPod/.test(userAgent) && !/Safari\//.test(userAgent)) return true;
  return /FBAN|FBAV|FB_IAB|Instagram|Zalo|Line\/|MicroMessenger|TikTok|musical_ly|BytedanceWebview/i.test(
    userAgent,
  );
}

const noopSubscribe = () => () => {};

type GoogleSignInProps = {
  onCredential: (credential: string) => void;
  disabled: boolean;
  isServerDisabled: boolean;
  t: { label: string; notConfigured: string };
};

// Nút Google: có client ID ⇒ nút GIS chính hãng; thiếu ID/lỗi/backend chưa bật ⇒ nút báo "đang cấu hình"
export function GoogleSignIn({ onCredential, disabled, isServerDisabled, t }: GoogleSignInProps) {
  // Máy chủ chưa biết User-Agent ⇒ coi như trình duyệt thường
  const isEmbedded = useSyncExternalStore(
    noopSubscribe,
    () => isEmbeddedBrowser(navigator.userAgent),
    () => false,
  );
  const [isFailed, setIsFailed] = useState(false);
  const [isNoticeShown, setIsNoticeShown] = useState(false);
  const buttonRef = useRef<HTMLDivElement>(null);
  // Callback của Google luôn gọi hàm mới nhất
  const onCredentialRef = useRef(onCredential);
  useEffect(() => {
    onCredentialRef.current = onCredential;
  }, [onCredential]);

  function renderButton() {
    const id = window.google?.accounts.id;
    const parent = buttonRef.current;
    if (!id || !parent) return;
    id.initialize({
      client_id: CLIENT_ID,
      callback: ({ credential }) => onCredentialRef.current(credential),
      ux_mode: "popup",
      context: "signin",
    });
    id.renderButton(parent, {
      type: "standard",
      theme: "outline",
      size: "large",
      text: "signin_with",
      shape: "rectangular",
      logo_alignment: "center",
      locale: "vi",
      width: Math.min(parent.offsetWidth, MAX_BUTTON_WIDTH),
    });
  }

  if (isEmbedded) return null;

  if (CLIENT_ID && !isFailed && !isServerDisabled) {
    return (
      <>
        {/* Giữ chỗ cao bằng nút để trang không nhảy */}
        <div
          ref={buttonRef}
          inert={disabled}
          className="flex min-h-11 items-center justify-center transition-opacity inert:opacity-50"
        />
        <Script
          src={GIS_SRC}
          strategy="afterInteractive"
          onReady={renderButton}
          onError={() => setIsFailed(true)}
        />
      </>
    );
  }

  return (
    <>
      <Button
        type="button"
        variant="secondary"
        block
        disabled={disabled}
        onClick={() => setIsNoticeShown(true)}
      >
        <span className="flex items-center gap-2">
          <GoogleLogoIcon />
          {t.label}
        </span>
      </Button>
      {(isNoticeShown || isServerDisabled) && <Alert variant="info">{t.notConfigured}</Alert>}
    </>
  );
}
