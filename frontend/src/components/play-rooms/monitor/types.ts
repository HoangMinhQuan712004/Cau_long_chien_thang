import type { components } from "@/lib/api/schema";

// Theo dõi sân (T-069): kiểu sinh từ schema.d.ts (không sửa tay).
type S = components["schemas"];

export type MonitorPerson = S["MonitorPerson"];
export type MonitorMatch = S["MonitorMatch"];
export type MonitorRoom = S["MonitorRoom"];
export type MonitorRoomStatus = MonitorRoom["status"];
export type MonitorCourt = S["MonitorCourt"];
export type MonitorDay = S["MonitorDay"];
export type MonitorMember = S["MonitorMember"];
export type MonitorRankingRow = S["MonitorRankingRow"];
export type MonitorRoomDetail = S["MonitorRoomDetail"];
