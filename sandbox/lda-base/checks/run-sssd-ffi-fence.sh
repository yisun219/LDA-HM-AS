#!/usr/bin/env bash
# FFI fence for the sssd card: a consumer compiled ONCE against the baseline
# NSS module ABI calls _nss_sss_getpwnam_r directly through dlopen; running
# it unmodified against the candidate module and daemon with identical
# results is the drop-in proof at the exact glibc NSS boundary.
set -euo pipefail
. /opt/lda/harness/checks/sssd-workbench.sh
/opt/lda/harness/checks/ensure-pkg-candidate.sh

consumer=/opt/lda/fixtures/sssd/nss-ffi-consumer
if ! test -x "$consumer"; then
  cat >"$consumer.c" <<'C'
#include <dlfcn.h>
#include <pwd.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

typedef int (*getpwnam_r_fn)(const char *, struct passwd *, char *, size_t, int *);

int main(int argc, char **argv) {
  if (argc < 2) return 64;
  void *so = dlopen("libnss_sss.so.2", RTLD_NOW);
  if (!so) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 69; }
  getpwnam_r_fn lookup = (getpwnam_r_fn)dlsym(so, "_nss_sss_getpwnam_r");
  if (!lookup) { fprintf(stderr, "dlsym: %s\n", dlerror()); return 69; }
  uint64_t hash = UINT64_C(1469598103934665603);
  char buffer[4096];
  for (int i = 1; i < argc; ++i) {
    struct passwd entry;
    int nss_errno = 0;
    int status = lookup(argv[i], &entry, buffer, sizeof buffer, &nss_errno);
    char line[512];
    if (status == 1) {
      snprintf(line, sizeof line, "%s:%u:%s", entry.pw_name,
               (unsigned)entry.pw_uid, entry.pw_gecos ? entry.pw_gecos : "");
    } else {
      snprintf(line, sizeof line, "miss:%s:%d", argv[i], status);
    }
    for (const char *p = line; *p; ++p) { hash ^= (unsigned char)*p; hash *= UINT64_C(1099511628211); }
  }
  printf("%016llx\n", (unsigned long long)hash);
  return 0;
}
C
  cc -O2 -Wall -Werror -o "$consumer" "$consumer.c" -ldl
fi

names=()
for i in 0 7 42 137 999 2999; do names+=("lda_u$i"); done
names+=(lda_missing1 lda_missing77)

lda_sssd_install_mode baseline
lda_sssd_restart
base="$("$consumer" "${names[@]}")"
lda_sssd_install_mode candidate
lda_sssd_restart
cand="$("$consumer" "${names[@]}")"
test "$base" = "$cand" || {
  echo "precompiled NSS consumer results differ: $base vs $cand" >&2
  exit 1
}
printf 'precompiled sssd NSS consumer hash=%s\n' "$cand"
