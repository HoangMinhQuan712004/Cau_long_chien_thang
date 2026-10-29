// Chế độ thử (OTP_TEST_MODE, chỉ link dev): backend trả mã trong response nên hiện ngay trên màn hình (T-013 AC29).
// Mã của Admin/nhân viên không bao giờ có ở đây (chỉ ghi log server).
export function TestOtpNotice({ code }: { code: string | null | undefined }) {
  if (!code) return null;
  return (
    <p
      role="status"
      className="rounded-lg border border-accent bg-accent/15 px-3 py-2 text-ui text-foreground"
    >
      Mã thử (chỉ link dev): <b className="font-semibold tracking-widest tabular-nums">{code}</b>
    </p>
  );
}
