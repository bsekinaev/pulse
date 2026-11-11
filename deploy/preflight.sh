#!/usr/bin/env bash
# PULSE-009. Диагностика VPS без изменения Docker, Git или конфигурации Caddy.
set -euo pipefail

PULSE_DIR="${PULSE_DIR:-/opt/pulse-demo}"
PULSE_CONTAINER="${PULSE_CONTAINER:-pulse-demo}"
CADDY_CONTAINER="${CADDY_CONTAINER:-sekinaev-production-caddy-1}"
CADDY_CONFIG="${CADDY_CONFIG:-/opt/sekinaev-site/deploy/Caddyfile.production-only}"
EDGE_NETWORK="${EDGE_NETWORK:-pulse_public_edge}"
PULSE_DOMAIN="${PULSE_DOMAIN:-pulse.bsekinaev.ru}"
PUBLIC_IP="${PUBLIC_IP:-137.22.144.111}"

fail() {
  printf 'PULSE_PREFLIGHT_FAIL=%s\n' "$1" >&2
  exit 1
}

echo "=== PULSE-009: READ-ONLY PREFLIGHT ==="
for command in git docker curl getent; do
  command -v "$command" >/dev/null || fail "missing_$command"
done
test -d "$PULSE_DIR/.git" || fail "git_repo_absent"
test -f "$CADDY_CONFIG" || fail "caddy_config_absent"
cd "$PULSE_DIR"

echo "=== 1. ВЕРСИЯ И ИЗМЕНЕНИЯ ==="
echo "GIT_SHA=$(git rev-parse HEAD)"
if [ -n "$(git status --porcelain)" ]; then
  echo "GIT_WORKTREE=CLEAN_REQUIRED"
else
  echo "GIT_WORKTREE=CLEAN"
fi

echo "=== 2. COMPOSE ==="
docker compose config --quiet || fail "invalid_compose"
echo "COMPOSE_CONFIG=PASS"

echo "=== 3. DNS ==="
DNS_IP=$(getent ahostsv4 "$PULSE_DOMAIN" | awk 'NR==1 {first=$1} END {print first}')
echo "DNS_IP=$DNS_IP"
test "$DNS_IP" = "$PUBLIC_IP" || fail "dns_mismatch"

echo "=== 4. КОНТЕЙНЕРЫ ==="
PULSE_STATUS=$(docker inspect "$PULSE_CONTAINER" --format '{{.State.Status}}') || fail "pulse_absent"
PULSE_HEALTH=$(docker inspect "$PULSE_CONTAINER" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}') || fail "pulse_health_missing"
CADDY_STATUS=$(docker inspect "$CADDY_CONTAINER" --format '{{.State.Status}}') || fail "caddy_absent"
echo "PULSE_STATUS=$PULSE_STATUS"
echo "PULSE_HEALTH=$PULSE_HEALTH"
echo "CADDY_STATUS=$CADDY_STATUS"
test "$PULSE_STATUS" = "running" || fail "pulse_not_running"
test "$PULSE_HEALTH" = "healthy" || fail "pulse_not_healthy"
test "$CADDY_STATUS" = "running" || fail "caddy_not_running"

echo "=== 5. СЕТЬ И ТОПОЛОГИЯ ==="
docker network inspect "$EDGE_NETWORK" >/dev/null || fail "edge_network_absent"
for name in "$PULSE_CONTAINER" "$CADDY_CONTAINER"; do
  docker inspect "$name" --format '{{json .NetworkSettings.Networks}}' \
    | grep -Fq "\"$EDGE_NETWORK\"" || fail "missing_edge_for_$name"
done
docker exec "$CADDY_CONTAINER" wget -qO- "http://$PULSE_CONTAINER:8000/health" >/dev/null \
  || fail "caddy_to_pulse_unreachable"
echo "EDGE_NETWORK=PASS"

echo "=== 6. SQLITE VOLUME ==="
VOLUME=$(docker inspect "$PULSE_CONTAINER" --format '{{range .Mounts}}{{if eq .Destination "/var/lib/pulse"}}{{.Name}}{{end}}{{end}}')
test -n "$VOLUME" || fail "sqlite_volume_unknown"
docker volume inspect "$VOLUME" >/dev/null || fail "sqlite_volume_missing"
echo "SQLITE_VOLUME=$VOLUME"

echo "=== 7. CADDY ROUTE ==="
grep -Eq '^[[:space:]]*pulse\.bsekinaev\.ru[[:space:]]*\{' "$CADDY_CONFIG" \
  || fail "pulse_route_absent"
docker exec "$CADDY_CONTAINER" caddy validate --config /etc/caddy/Caddyfile >/dev/null \
  || fail "invalid_caddy_config"
echo "CADDY_CONFIG=PASS"

echo "=== 8. HTTPS SMOKE ==="
curl -fsS --max-time 10 -o /dev/null "https://$PULSE_DOMAIN/login" \
  || fail "pulse_https_failure"
curl -fsS --max-time 10 -o /dev/null https://bsekinaev.ru/ \
  || fail "main_site_failure"
echo "PULSE_HTTPS=PASS"
echo "MAIN_SITE_HTTPS=PASS"
echo "PULSE_PREFLIGHT=PASS"
