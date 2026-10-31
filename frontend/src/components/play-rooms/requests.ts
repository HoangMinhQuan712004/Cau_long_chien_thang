import "client-only";
import { looseApi } from "@/lib/api/client";
import { toApiError, type WriteResult, write } from "@/lib/api/write";
import type { Read } from "@/components/member-area/requests";
import type { Format, MatchList, NotificationList, Ranking, RoomDetail, RoomList } from "./types";

// Lời gọi API phòng chơi (T-017). Đọc → `Read<T>`; ghi → `write()` (Idempotency-Key). Ghi kèm `version` phòng.

const P = "/api/v1/member-area";

async function read<T>(call: () => Promise<{ data?: unknown; error?: unknown; response: Response }>): Promise<Read<T>> {
  try {
    const { data, error, response } = await call();
    if (response.ok && data !== undefined) return { ok: true, data: data as T };
    return { ok: false, error: toApiError(error, response.status) };
  } catch {
    return { ok: false, error: { status: 0, code: "E-017", message: "Mất kết nối. Vui lòng thử lại.", extra: {} } };
  }
}

const post = <T = unknown>(path: string, body: Record<string, unknown> = {}): Promise<WriteResult<T>> =>
  write((key) => looseApi.POST(`${P}${path}`, { body, headers: { "Idempotency-Key": key } }));

export type RoomsApi = {
  listRooms(scope: "all" | "mine"): Promise<Read<RoomList>>;
  getRoom(id: number): Promise<Read<RoomDetail>>;
  listMatches(id: number, format: Format | "all"): Promise<Read<MatchList>>;
  getRanking(id: number, format: Format | "all"): Promise<Read<Ranking>>;
  requestJoin(id: number, version: number): Promise<WriteResult<unknown>>;
  cancelRequest(id: number): Promise<WriteResult<unknown>>;
  decide(id: number, requestId: number, approve: boolean, version: number): Promise<WriteResult<unknown>>;
  invite(id: number, phone: string, version: number): Promise<WriteResult<unknown>>;
  answerInvite(inviteId: number, accept: boolean): Promise<WriteResult<unknown>>;
  leave(id: number, version: number): Promise<WriteResult<unknown>>;
  kick(id: number, memberId: number, version: number): Promise<WriteResult<unknown>>;
  transferHost(id: number, memberId: number, version: number): Promise<WriteResult<unknown>>;
  setFormat(id: number, format: Format, version: number): Promise<WriteResult<unknown>>;
  draw(id: number, version: number): Promise<WriteResult<unknown>>;
  start(id: number, version: number): Promise<WriteResult<unknown>>;
  saveResult(id: number, no: number, scoreA: number, scoreB: number, version: number): Promise<WriteResult<unknown>>;
  listNotifications(): Promise<Read<NotificationList>>;
  readAll(): Promise<WriteResult<unknown>>;
  readOne(id: number): Promise<WriteResult<unknown>>;
};

const real: RoomsApi = {
  listRooms: (scope) => read(() => looseApi.GET(`${P}/rooms`, { params: { query: { scope } } })),
  getRoom: (id) => read(() => looseApi.GET(`${P}/rooms/{id}`, { params: { path: { id } } })),
  listMatches: (id, format) =>
    read(() => looseApi.GET(`${P}/rooms/{id}/matches`, { params: { path: { id }, query: format === "all" ? {} : { format } } })),
  getRanking: (id, format) =>
    read(() => looseApi.GET(`${P}/rooms/{id}/ranking`, { params: { path: { id }, query: format === "all" ? {} : { format } } })),
  requestJoin: (id, version) => post(`/rooms/${id}/join-requests`, { version }),
  cancelRequest: (id) => write((key) => looseApi.DELETE(`${P}/rooms/${id}/join-requests/mine`, { headers: { "Idempotency-Key": key } })),
  decide: (id, rid, approve, version) => post(`/rooms/${id}/join-requests/${rid}/${approve ? "approve" : "reject"}`, { version }),
  invite: (id, phone, version) => post(`/rooms/${id}/invites`, { phone, version }),
  answerInvite: (iid, accept) => post(`/invites/${iid}/${accept ? "accept" : "decline"}`),
  leave: (id, version) => post(`/rooms/${id}/leave`, { version }),
  kick: (id, mid, version) => post(`/rooms/${id}/members/${mid}/kick`, { version }),
  transferHost: (id, mid, version) => post(`/rooms/${id}/members/${mid}/transfer-host`, { version }),
  setFormat: (id, format, version) =>
    write((key) => looseApi.PUT(`${P}/rooms/${id}/format`, { body: { format, version }, headers: { "Idempotency-Key": key } })),
  draw: (id, version) => post(`/rooms/${id}/draw`, { version }),
  start: (id, version) => post(`/rooms/${id}/start`, { version }),
  saveResult: (id, no, a, b, version) => post(`/rooms/${id}/matches/${no}/result`, { score_a: a, score_b: b, version }),
  listNotifications: () => read(() => looseApi.GET(`${P}/notifications`, {})),
  readAll: () => post("/notifications/read-all"),
  readOne: (id) => post(`/notifications/${id}/read`),
};

export const roomsApi: RoomsApi = real;
