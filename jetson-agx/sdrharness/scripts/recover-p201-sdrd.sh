#!/usr/bin/env bash
set -euo pipefail

readonly p201_host="192.168.1.10"
readonly p201_password_file="/home/jetson/.config/sdrharness/p201-root.password"
readonly p201_known_hosts="/home/jetson/.ssh/known_hosts"
readonly recovery_lock="/run/sdrharness-p201-recovery/recovery.lock"
readonly controller="/home/jetson/.local/lib/sdrharness/bin/sdr-agent-controller"

umask 077

for command_name in flock nc ssh sshpass stat timeout; do
  command -v "${command_name}" >/dev/null 2>&1 || {
    echo "p201_recovery_error=missing_command command=${command_name}" >&2
    exit 2
  }
done
[[ -x "${controller}" ]] || {
  echo "p201_recovery_error=missing_controller" >&2
  exit 2
}
[[ -f "${p201_password_file}" && ! -L "${p201_password_file}" ]] || {
  echo "p201_recovery_error=invalid_password_file" >&2
  exit 2
}
[[ "$(stat -c '%a' "${p201_password_file}")" == "600" ]] || {
  echo "p201_recovery_error=password_permissions" >&2
  exit 2
}
[[ -f "${p201_known_hosts}" && ! -L "${p201_known_hosts}" ]] || {
  echo "p201_recovery_error=invalid_known_hosts" >&2
  exit 2
}

exec 9>"${recovery_lock}"
flock -n 9 || {
  echo "p201_recovery_error=already_running" >&2
  exit 75
}

nc -z -w 3 "${p201_host}" 22 || {
  echo "p201_recovery_error=ssh_unreachable" >&2
  exit 1
}

timeout 25 sshpass -f "${p201_password_file}" ssh \
  -o BatchMode=no \
  -o ConnectTimeout=5 \
  -o IdentitiesOnly=yes \
  -o PreferredAuthentications=password \
  -o PubkeyAuthentication=no \
  -o StrictHostKeyChecking=yes \
  -o UserKnownHostsFile="${p201_known_hosts}" \
  "root@${p201_host}" /bin/sh <<'P201_RECOVERY'
set -eu

daemon=/sd/sdr-agent/current/sdrd
config=/sd/sdr-agent/current/sdrd.conf
init_source=/sd/sdr-agent/current/S60sdrd
init_target=/etc/init.d/S60sdrd

[ -x "${daemon}" ] && [ -r "${config}" ] && [ -x "${init_source}" ] || {
  echo 'p201_recovery_error=missing_persistent_release' >&2
  exit 1
}
pid_count="$(pidof sdrd 2>/dev/null | wc -w)"
listener_count="$(netstat -lnt 2>/dev/null | grep -c ':43110 ' || true)"

if [ "${pid_count}" -eq 1 ] && [ "${listener_count}" -eq 1 ]; then
  pid="$(pidof sdrd)"
  [ "$(readlink "/proc/${pid}/exe")" = "${daemon}" ] || {
    echo 'p201_recovery_error=unexpected_executable' >&2
    exit 1
  }
  action=already_running
elif [ "${pid_count}" -eq 0 ] && [ "${listener_count}" -eq 0 ]; then
  cp "${init_source}" "${init_target}.new"
  chmod 0755 "${init_target}.new"
  mv "${init_target}.new" "${init_target}"
  "${init_target}" start
  action=started
else
  echo "p201_recovery_error=inconsistent_prestart_state pid_count=${pid_count} listener_count=${listener_count}" >&2
  exit 1
fi

pid_count="$(pidof sdrd 2>/dev/null | wc -w)"
listener_count="$(netstat -lnt 2>/dev/null | grep -c ':43110 ' || true)"
[ "${pid_count}" -eq 1 ] && [ "${listener_count}" -eq 1 ] || {
  echo "p201_recovery_error=poststart_state pid_count=${pid_count} listener_count=${listener_count}" >&2
  exit 1
}
echo "p201_recovery_action=${action} pid_count=${pid_count} listener_count=${listener_count} daemon_sha256=$(sha256sum "${daemon}" | awk '{print $1}')"
P201_RECOVERY

nc -z -w 3 "${p201_host}" 43110 || {
  echo "p201_recovery_error=sdrd_unreachable" >&2
  exit 1
}
"${controller}" \
  --mode observe \
  --sdrd "${p201_host}:43110" \
  --sdrd-timeout-ms 5000 \
  --request /dev/null >/dev/null
echo "p201_recovery_result=healthy"
