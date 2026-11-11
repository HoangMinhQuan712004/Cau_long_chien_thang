// Theo dõi sân (T-069). Kiểu theo contract trong spec; sau khi merge nhánh BE thì thay bằng kiểu sinh từ schema.d.ts.
// TẠM (T-069): bỏ file này, dùng `components["schemas"]["MonitorDay"]`... khi schema.d.ts có.

export type MonitorPerson = {
  customer_id: number;
  full_name: string;
  nickname: string | null;
  member_code: string | null;
  tier: string | null;
  avatar_url: string | null;
};

export type MonitorMatch = {
  no: number;
  format: "2v2" | "1v1";
  status: string;
  team_a: MonitorPerson[];
  team_b: MonitorPerson[];
  score_a: number | null;
  score_b: number | null;
  winner: "a" | "b" | null;
  started_at: string | null;
  ended_at: string | null;
};

export type MonitorRoomStatus = "upcoming" | "playing" | "ended" | "cancelled";

export type MonitorRoom = {
  room_id: number;
  booking_code: string;
  start_at: string;
  end_at: string;
  status: MonitorRoomStatus;
  host: MonitorPerson;
  member_count: number;
  format: "2v2" | "1v1";
  min_tier: string | null;
  max_tier: string | null;
  matches_finished: number;
  current_match: MonitorMatch | null;
  last_match: MonitorMatch | null;
};

export type MonitorCourt = {
  resource_code: string;
  resource_name: string;
  is_active: boolean;
  rooms: MonitorRoom[];
};

export type MonitorDay = { date: string; courts: MonitorCourt[] };

export type MonitorMember = MonitorPerson & { queue_state: string };

export type MonitorRankingRow = {
  rank: number;
  person: MonitorPerson;
  wins: number;
  losses: number;
  played: number;
  win_rate: number;
};

export type MonitorRoomDetail = {
  room: MonitorRoom;
  members: MonitorMember[];
  matches: MonitorMatch[];
  ranking: MonitorRankingRow[];
};
