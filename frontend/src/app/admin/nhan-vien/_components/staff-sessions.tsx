import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import type { StaffSession } from "@/lib/api/server";
import { formatDate, formatTime } from "@/lib/format";
import { type StaffTexts, useStaffSubmit } from "./staff-form-kit";

type SessionsProps = {
  t: StaffTexts;
  staffId: number;
  onChanged: () => void;
};

const formatDateTime = (iso: string) => `${formatTime(iso)} ${formatDate(iso)}`;

// Phiên đang mở của một nhân viên + đăng xuất từ xa từng phiên
export function StaffSessions({ t, staffId, onChanged }: SessionsProps) {
  // null = đang tải
  const [sessions, setSessions] = useState<StaffSession[] | null>(null);
  const [revokingId, setRevokingId] = useState<number | null>(null);
  const { isPending, error, setError, submit } = useStaffSubmit(t);

  useEffect(() => {
    let isCurrent = true;
    api
      .GET("/api/v1/admin/staff/{staff_id}/sessions", { params: { path: { staff_id: staffId } } })
      .then(({ data }) => {
        if (!isCurrent) return;
        if (data) setSessions(data);
        else setError(t.errors.generic);
      })
      .catch(() => isCurrent && setError(t.errors.network));
    return () => {
      isCurrent = false;
    };
  }, [staffId, t, setError]);

  async function revoke(sessionId: number) {
    setRevokingId(sessionId);
    const path = { staff_id: staffId, session_id: sessionId };
    const ok = await submit(() =>
      api.DELETE("/api/v1/admin/staff/{staff_id}/sessions/{session_id}", { params: { path } }),
    );
    if (!ok) return;
    setSessions((list) => list?.filter((s) => s.id !== sessionId) ?? null);
    onChanged();
  }

  if (sessions === null && !error) {
    return (
      <div aria-hidden className="h-14 animate-pulse rounded-lg bg-background motion-reduce:animate-none" />
    );
  }

  return (
    <div className="flex flex-col gap-3" aria-live="polite">
      {error && <Alert variant="error">{error}</Alert>}
      {sessions?.length === 0 && <p className="text-ui text-muted">{t.sessionsEmpty}</p>}
      {sessions && sessions.length > 0 && (
        <ul className="flex flex-col divide-y rounded-lg border">
          {sessions.map((s) => (
            <li key={s.id} className="flex flex-col gap-2 p-3 sm:flex-row sm:items-center">
              <div className="min-w-0 flex-1 text-ui">
                <p className="truncate font-semibold">{s.user_agent ?? t.unknownDevice}</p>
                <p className="text-muted tabular-nums">
                  {[
                    s.ip_masked,
                    t.sessionLoggedIn.replace("{time}", formatDateTime(s.created_at)),
                    t.sessionExpires.replace("{time}", formatDateTime(s.expires_at)),
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
              <Button
                type="button"
                variant="secondary"
                loading={isPending && revokingId === s.id}
                disabled={isPending}
                onClick={() => revoke(s.id)}
              >
                {t.revoke}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
