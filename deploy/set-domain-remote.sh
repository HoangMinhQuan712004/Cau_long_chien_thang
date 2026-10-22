#!/usr/bin/env bash
# Chạy TRÊN SERVER (root), được gọi bởi deploy/set-domain.ps1.
# Dùng: bash set-domain-remote.sh <domain> <with_www 0|1> [old_host]
set -euo pipefail

DOMAIN="$1"
WITH_WWW="$2"
OLD_HOST="${3:-}"
APP_DIR=/opt/caulong
CADDYFILE=/etc/caddy/Caddyfile

domain_re='^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$'
[[ "$DOMAIN" =~ $domain_re ]] || { echo "Domain không hợp lệ: $DOMAIN" >&2; exit 1; }
[[ -z "$OLD_HOST" || "$OLD_HOST" =~ $domain_re ]] || { echo "old_host không hợp lệ" >&2; exit 1; }
grep -q '^IMAGE_TAG=' "$APP_DIR/.env" || {
  echo "Thiếu IMAGE_TAG trong $APP_DIR/.env – hãy chạy CD một lần trước." >&2
  exit 1
}

# Các host phụ chuyển hướng 301 về domain chính (tránh trùng nội dung khi Google index)
redirects=()
[[ "$WITH_WWW" == 1 ]] && redirects+=("www.$DOMAIN")
[[ -n "$OLD_HOST" && "$OLD_HOST" != "$DOMAIN" && "$OLD_HOST" != "www.$DOMAIN" ]] && redirects+=("$OLD_HOST")

echo "== Caddy: $DOMAIN${redirects:+ (redirect: ${redirects[*]})}"
{
  echo "# Sinh bởi deploy/set-domain.ps1"
  echo "$DOMAIN {"
  printf '\tencode zstd gzip\n\treverse_proxy 127.0.0.1:3000\n}\n'
  if ((${#redirects[@]})); then
    printf '\n%s {\n' "$(printf '%s, ' "${redirects[@]}" | sed 's/, $//')"
    printf '\tredir https://%s{uri} permanent\n}\n' "$DOMAIN"
  fi
} > "$CADDYFILE.new"
caddy validate --config "$CADDYFILE.new" --adapter caddyfile >/dev/null
cp "$CADDYFILE" "$CADDYFILE.bak.$(date +%Y%m%d%H%M%S)"
mv "$CADDYFILE.new" "$CADDYFILE"
systemctl reload caddy

echo "== App: CORS_ORIGINS"
sed -i "s|^CORS_ORIGINS=.*|CORS_ORIGINS=[\"https://$DOMAIN\"]|" "$APP_DIR/.env"
(cd "$APP_DIR" && docker compose up -d --quiet-pull 2>&1 | tail -3)

echo "== Chờ chứng chỉ HTTPS"
for _ in $(seq 1 40); do
  if curl -fsS -o /dev/null --max-time 5 "https://$DOMAIN/robots.txt"; then
    echo "HTTPS OK: https://$DOMAIN"
    exit 0
  fi
  sleep 3
done
echo "Chưa lấy được chứng chỉ – xem: journalctl -u caddy -n 50" >&2
exit 1
