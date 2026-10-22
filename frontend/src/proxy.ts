import { type NextRequest, NextResponse } from "next/server";

// Kiểm tra lạc quan: chỉ xem có cookie phiên hay không để chuyển hướng sớm.
// Quyền thật (role) luôn được backend kiểm tra trên từng API.
export function proxy(request: NextRequest) {
  if (request.cookies.has("access_token")) return NextResponse.next();

  const login = new URL("/dang-nhap", request.url);
  login.searchParams.set("next", request.nextUrl.pathname + request.nextUrl.search);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/tai-khoan/:path*", "/admin/:path*"],
};
