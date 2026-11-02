import "client-only";
import { api } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";
import { read } from "@/components/web-booking/requests";
import type { MemberCalendar } from "@/components/web-booking/types";

// T-023: lịch đặt sân của hội viên (ô "Sân của bạn", ô sự kiện) + chi tiết đơn của mình.

export type MyBooking = components["schemas"]["MemberOrder"];

export const getMemberCalendar = (date: string) =>
  read<MemberCalendar>(() => api.GET("/api/v1/member-area/booking-calendar", { params: { query: { date } } }));

export const getMyBooking = (orderCode: string) =>
  read<MyBooking>(() => api.GET("/api/v1/member-area/bookings/{order_code}", { params: { path: { order_code: orderCode } } }));
