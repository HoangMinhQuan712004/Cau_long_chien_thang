import type { components } from "@/lib/api/schema";

// Phòng chơi (T-017): type sinh từ schema.d.ts. Mốc 2 (bốc, bắt đầu, tỉ số, lịch sử, xếp hạng) còn là giả định của FE.

type S = components["schemas"];

export const MAX_MEMBERS = 8;

export type Format = "2v2" | "1v1";
export const FORMAT_LABEL: Record<Format, string> = { "2v2": "2 vs 2", "1v1": "1 vs 1" };
export const FORMAT_NEED: Record<Format, number> = { "2v2": 4, "1v1": 2 };

/** Người trong phòng: tên hiển thị (biệt danh nếu có, không thì họ tên) + ảnh. KHÔNG có SĐT. */
export type Person = S["PersonOut"];
export type RoomCard = S["RoomCard"];
export type RoomList = S["RoomList"];
export type RoomDetail = S["RoomDetail"];
export type RoomMember = S["RoomMemberOut"];
/** Yêu cầu vào phòng / lời mời đang chờ (Host thấy). */
export type PendingPerson = S["PendingPersonOut"];
export type Player = S["PlayerOut"];
export type CurrentMatch = S["CurrentMatchOut"];
export type NotificationItem = S["NotificationOut"];
export type NotificationList = S["NotificationList"];
export type MyRole = RoomDetail["my_role"];

export type MatchRow = S["MatchRow"];
export type MatchList = S["MatchList"];
export type RankingRow = S["RankingRow"];
export type Ranking = S["Ranking"];
