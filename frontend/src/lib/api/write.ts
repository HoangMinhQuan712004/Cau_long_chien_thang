import "client-only";
import { beginReconnect } from "../feedback";

// Hạ tầng gọi API ghi an toàn (ADR-004 S10): mỗi lần bấm nút = một Idempotency-Key (UUID v4),
// GIỮ NGUYÊN key khi tự thử lại (mất mạng, 502/503/504, 409 E-SEC-3), để backend trả kết quả cũ thay vì ghi hai lần.

export type ApiError = {
  status: number;
  /** Mã lỗi nghiệp vụ (`detail.code`), ví dụ `E-CFG-7`. Rỗng với lỗi định dạng 422 mặc định của FastAPI. */
  code?: string;
  message: string;
  /** Phần còn lại của `detail` (ví dụ `items`, `more` của E-CFG-3/4). */
  extra: Record<string, unknown>;
};

export type WriteResult<T> = { ok: true; data: T; status: number } | { ok: false; error: ApiError };

type Sent<T> = { data?: T; error?: unknown; response: Response };

const GIVE_UP_MS = 2 * 60 * 1000;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** UUID v4; `crypto.randomUUID` chỉ có ở ngữ cảnh bảo mật nên có đường dự phòng. */
export function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

/** Chuẩn hóa body lỗi của backend thành `ApiError` (map theo `detail.code`, không phụ thuộc câu chữ). */
export function toApiError(error: unknown, status: number): ApiError {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const { code, message, ...extra } = detail as Record<string, unknown>;
    return {
      status,
      code: typeof code === "string" ? code : undefined,
      message: typeof message === "string" && message ? message : DEFAULT_MESSAGE,
      extra,
    };
  }
  if (typeof detail === "string") return { status, message: detail, extra: {} };
  if (Array.isArray(detail)) {
    return { status, message: "Dữ liệu chưa hợp lệ. Vui lòng kiểm tra lại các ô đã nhập.", extra: {} };
  }
  return { status, message: DEFAULT_MESSAGE, extra: {} };
}

const DEFAULT_MESSAGE = "Có lỗi xảy ra, vui lòng thử lại.";

/** Câu thay thế khi lỗi không có `message` từ server hoặc cần câu riêng theo mã. */
const MESSAGE_BY_CODE: Record<string, string> = {
  "E-AUTH-1": "Phiên đăng nhập đã hết. Vui lòng đăng nhập lại.",
  "E-AUTH-2": "Bạn không có quyền thực hiện thao tác này.",
  "E-SEC-1": "Yêu cầu bị từ chối vì nguồn gửi không hợp lệ. Hãy tải lại trang rồi thử lại.",
  "E-SEC-5": "Thao tác quá nhanh. Vui lòng chờ một lát rồi thử lại.",
  "E-SEC-6": "Dữ liệu gửi lên quá lớn.",
  "E-017": "Mất kết nối. Vui lòng chờ trong giây lát, hệ thống đang thử kết nối lại.",
};

export const errorText = (e: ApiError) => (e.code && MESSAGE_BY_CODE[e.code] && e.message === DEFAULT_MESSAGE ? MESSAGE_BY_CODE[e.code] : e.message);

const retryAfterMs = (r: Response) => {
  const s = Number(r.headers.get("Retry-After"));
  return Number.isFinite(s) && s > 0 ? Math.min(s, 10) * 1000 : 2000;
};

/**
 * Gửi một lệnh ghi. `send` nhận Idempotency-Key và gọi `api.POST/PUT/PATCH/DELETE`
 * (truyền `headers: { "Idempotency-Key": key }`). Hàm tự thử lại với CÙNG key khi mất kết nối.
 */
export async function write<T>(
  send: (idempotencyKey: string) => Promise<Sent<T>>,
  /** `retryRateLimit: false` cho lệnh bị khóa theo thời gian (vd nhập sai mật khẩu): báo ngay, không tự thử lại. */
  opts: { retryRateLimit?: boolean } = {},
): Promise<WriteResult<T>> {
  const key = newIdempotencyKey();
  const started = Date.now();
  let endReconnect: (() => void) | null = null;
  let inflightRetries = 0;
  let rateRetries = 0;

  try {
    for (let attempt = 0; ; attempt++) {
      let res: Sent<T> | null = null;
      try {
        res = await send(key);
      } catch {
        res = null; // lỗi mạng
      }

      const status = res?.response.status ?? 0;
      const offline = !res || status === 502 || status === 503 || status === 504;
      if (offline) {
        if (Date.now() - started > GIVE_UP_MS) {
          return { ok: false, error: { status: 0, code: "E-017", message: MESSAGE_BY_CODE["E-017"], extra: {} } };
        }
        endReconnect ??= beginReconnect();
        await sleep(Math.min(1000 + attempt * 1000, 5000));
        continue;
      }
      endReconnect?.();
      endReconnect = null;

      if (res!.error === undefined && status < 400) {
        return { ok: true, data: res!.data as T, status };
      }

      const error = toApiError(res!.error, status);
      // Cùng key đang chạy ở request khác: chờ giây lát rồi gửi lại sẽ nhận kết quả cũ.
      if (error.code === "E-SEC-3" && inflightRetries < 5) {
        inflightRetries += 1;
        await sleep(700);
        continue;
      }
      if (status === 429 && opts.retryRateLimit !== false && rateRetries < 2) {
        rateRetries += 1;
        await sleep(retryAfterMs(res!.response));
        continue;
      }
      return { ok: false, error };
    }
  } finally {
    endReconnect?.();
  }
}
