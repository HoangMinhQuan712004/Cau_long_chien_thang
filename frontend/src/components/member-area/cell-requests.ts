import "client-only";
import { looseApi } from "@/lib/api/client";
import { read } from "@/components/web-booking/requests";
import type { PayStatus, WebCalendar } from "@/components/web-booking/types";

// T-023: lịch đặt sân của hội viên (ô "Sân của bạn", ô sự kiện) + mua vé online.
// TODO(T-023): BE chưa handoff ⇒ kiểu viết tay theo spec và gọi qua `looseApi`; sau khi merge `be/T-023-ve-online` đổi sang `api` + kiểu của schema.d.ts.


export type MyBooking = {
  order_code: string;
  play_date: string;
  source: "online" | "counter";
  pay_status: PayStatus;
  amount: number;
  items: { code: string; resource_name: string; start_time: string; end_time: string; hours: number; amount: number; pay_status: PayStatus }[];
};

export const getMemberCalendar = (date: string) =>
  read<WebCalendar>(() => looseApi.GET("/api/v1/member-area/booking-calendar", { params: { query: { date } } }));

export const getMyBooking = (orderCode: string) =>
  read<MyBooking>(() => looseApi.GET("/api/v1/member-area/bookings/{order_code}", { params: { path: { order_code: orderCode } } }));
