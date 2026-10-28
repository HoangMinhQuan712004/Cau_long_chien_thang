import { type NextRequest, NextResponse } from "next/server";

// Chuyển hướng sớm khi thiếu cookie phiên; quyền thật luôn kiểm ở server/backend
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  // Khu quản trị: phiên `admin_session`; khách: JWT `access_token`; cả hai dùng chung màn /dang-nhap
  const isAdmin = pathname.startsWith("/admin");
  if (request.cookies.has(isAdmin ? "admin_session" : "access_token")) return NextResponse.next();

  const login = new URL("/dang-nhap", request.url);
  login.searchParams.set("next", pathname + search);
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/tai-khoan/:path*", "/admin/:path*"],
};
