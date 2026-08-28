#!/usr/bin/env bash
# Soup workbench: a precompiled dlopen consumer for the libsoup3 header
# layer (the FFI surface proof and the micro benchmark engine) plus helpers.
# The consumer is built ONCE against whatever libsoup headers describe at
# compile time - it dlopens libsoup-3.0.so.0, so running it unmodified
# against the candidate is the drop-in proof.
set -euo pipefail
. /opt/lda/harness/checks/pkg-common.sh

SOUP_FIXDIR=/opt/lda/fixtures/soup

lda_soup_prepare() {
  mkdir -p "$SOUP_FIXDIR"
  test -x "$SOUP_FIXDIR/soup-headers" && return 0
  cat >"$SOUP_FIXDIR/soup-headers.c" <<'C'
/* soup-headers: deterministic libsoup3 header-layer workloads via dlopen.
 *
 * argv[1]: corpus file (one header block per paragraph, fields "Name: value")
 * argv[2]: iterations over the whole corpus.
 * Exercises append/get_one/content-type/param and quality-list parsing and
 * prints one FNV chain hash of every extracted value as the last line.
 */
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef void *cptr;
typedef cptr (*headers_new_fn)(int);
typedef void (*append_fn)(cptr, const char *, const char *);
typedef const char *(*get_one_fn)(cptr, const char *);
typedef const char *(*get_content_type_fn)(cptr, cptr *);
typedef cptr (*parse_quality_fn)(const char *, cptr *);
typedef cptr (*parse_param_fn)(const char *);
typedef void (*free_list_fn)(cptr);
typedef void (*unref_fn)(cptr);
typedef unsigned int (*hash_table_size_fn)(cptr);
typedef void (*hash_table_destroy_fn)(cptr);

static uint64_t mix(uint64_t h, const char *s) {
  if (!s) return h * UINT64_C(1099511628211) ^ UINT64_C(0x9e3779b97f4a7c15);
  for (; *s; ++s) { h ^= (unsigned char)*s; h *= UINT64_C(1099511628211); }
  return h;
}

int main(int argc, char **argv) {
  if (argc < 3) return 64;
  void *soup = dlopen("libsoup-3.0.so.0", RTLD_NOW);
  if (!soup) { fprintf(stderr, "dlopen soup: %s\n", dlerror()); return 69; }
  void *glib = dlopen("libglib-2.0.so.0", RTLD_NOW);
  if (!glib) { fprintf(stderr, "dlopen glib: %s\n", dlerror()); return 69; }
  headers_new_fn headers_new = (headers_new_fn)dlsym(soup, "soup_message_headers_new");
  append_fn append = (append_fn)dlsym(soup, "soup_message_headers_append");
  get_one_fn get_one = (get_one_fn)dlsym(soup, "soup_message_headers_get_one");
  get_content_type_fn get_ct = (get_content_type_fn)dlsym(soup, "soup_message_headers_get_content_type");
  parse_quality_fn parse_quality = (parse_quality_fn)dlsym(soup, "soup_header_parse_quality_list");
  parse_param_fn parse_param = (parse_param_fn)dlsym(soup, "soup_header_parse_param_list");
  free_list_fn free_list = (free_list_fn)dlsym(soup, "soup_header_free_list");
  unref_fn headers_unref = (unref_fn)dlsym(soup, "soup_message_headers_unref");
  hash_table_destroy_fn ht_destroy = (hash_table_destroy_fn)dlsym(glib, "g_hash_table_destroy");
  hash_table_size_fn ht_size = (hash_table_size_fn)dlsym(glib, "g_hash_table_size");
  if (!headers_new || !append || !get_one || !get_ct || !parse_quality ||
      !parse_param || !free_list || !headers_unref || !ht_destroy || !ht_size) {
    fprintf(stderr, "dlsym: %s\n", dlerror());
    return 69;
  }

  FILE *stream = fopen(argv[1], "r");
  if (!stream) return 66;
  static char corpus[1 << 22];
  size_t total = fread(corpus, 1, sizeof(corpus) - 1, stream);
  corpus[total] = 0;
  fclose(stream);
  const int iterations = atoi(argv[2]);

  uint64_t h = UINT64_C(1469598103934665603);
  for (int it = 0; it < iterations; ++it) {
    char *cursor = corpus;
    while (*cursor) {
      /* one paragraph = one header block */
      cptr headers = headers_new(0 /* REQUEST */);
      while (*cursor && *cursor != '\n') {
        char *line_end = strchr(cursor, '\n');
        if (!line_end) line_end = cursor + strlen(cursor);
        char saved = *line_end;
        *line_end = 0;
        char *colon = strchr(cursor, ':');
        if (colon) {
          *colon = 0;
          const char *value = colon + 1;
          while (*value == ' ') ++value;
          append(headers, cursor, value);
          *colon = ':';
        }
        *line_end = saved;
        cursor = (*line_end ? line_end + 1 : line_end);
      }
      while (*cursor == '\n') ++cursor;

      h = mix(h, get_one(headers, "Host"));
      h = mix(h, get_one(headers, "Accept"));
      h = mix(h, get_one(headers, "X-Trace"));
      cptr params = NULL;
      const char *content_type = get_ct(headers, &params);
      h = mix(h, content_type);
      if (params) { h ^= ht_size(params); ht_destroy(params); }
      const char *accept = get_one(headers, "Accept");
      if (accept) {
        cptr unacceptable = NULL;
        cptr accepted = parse_quality(accept, &unacceptable);
        if (accepted) free_list(accepted);
        if (unacceptable) free_list(unacceptable);
      }
      const char *cache = get_one(headers, "Cache-Control");
      if (cache) {
        cptr parsed = parse_param(cache);
        if (parsed) { h ^= ht_size(parsed); ht_destroy(parsed); }
      }
      headers_unref(headers);
    }
  }
  printf("%016llx\n", (unsigned long long)h);
  return 0;
}
C
  cc -O2 -o "$SOUP_FIXDIR/soup-headers" "$SOUP_FIXDIR/soup-headers.c" -ldl
}

lda_soup_attribution() {
  local mode="${1:?mode required}"
  local library
  library="$(find "$(lda_pkg_libdir "$mode")" -name 'libsoup-3.0.so.0*' -type f | head -1)"
  test -n "$library" || { echo "no libsoup in $mode root" >&2; return 68; }
  printf 'soup %s library: %s\n' "$mode" "$library" >&2
}
