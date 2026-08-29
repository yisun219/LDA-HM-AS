#!/usr/bin/env bash
# Cairo workbench: builds the cairo-ops consumer once (dlopen, no -dev deps)
# and exposes helpers to run it against the baseline or candidate libcairo2.
# Beyond the original four workloads, the consumer carries three workloads
# that live entirely in cairo's own rasterization pipeline (stroker,
# tessellator, tor scan converter): stroke-dash, fill-tess, text-corpus.
# Their geometry comes from a seeded corpus so a hidden holdout can vary it.
set -euo pipefail
. /opt/lda/harness/checks/pkg-common.sh

CAIRO_FIXDIR=/opt/lda/fixtures/cairo

lda_cairo_prepare() {
  mkdir -p "$CAIRO_FIXDIR"
  test -x "$CAIRO_FIXDIR/cairo-ops" && return 0
  cat >"$CAIRO_FIXDIR/cairo-ops.c" <<'C'
/* cairo-ops: deterministic cairo workloads through the SELECTED libcairo.
 *
 * Workloads (argv[1]): png-load | paint | mask | text-path | all
 *                    | stroke-dash | fill-tess | text-corpus
 * argv[2]: iterations. argv[3...]: PNG fixtures (png-load only).
 * The corpus workloads read paths.txt / strings.txt from $LDA_CAIRO_PATHDIR
 * (default /opt/lda/fixtures/cairo-paths).
 * Prints one FNV chain hash of rendered pixels as the last line.
 */
#include <dlfcn.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef void *cptr;
typedef cptr (*surface_create_fn)(int, int, int);
typedef cptr (*from_png_fn)(const char *);
typedef cptr (*create_fn)(cptr);
typedef void (*void1_fn)(cptr);
typedef unsigned char *(*data_fn)(cptr);
typedef int (*int1_fn)(cptr);
typedef void (*rgba_fn)(cptr, double, double, double, double);
typedef void (*rect_fn)(cptr, double, double, double, double);
typedef cptr (*radial_fn)(double, double, double, double, double, double);
typedef void (*stop_fn)(cptr, double, double, double, double, double);
typedef void (*mask_fn)(cptr, cptr);
typedef void (*move_fn)(cptr, double, double);
typedef void (*text_fn)(cptr, const char *);
typedef void (*setsz_fn)(cptr, double);
typedef void (*curve_fn)(cptr, double, double, double, double, double, double);
typedef void (*dash_fn)(cptr, const double *, int, double);
typedef void (*seti_fn)(cptr, int);
typedef void (*setd_fn)(cptr, double);

static uint64_t hash_bytes(const unsigned char *d, size_t n) {
  uint64_t h = UINT64_C(1469598103934665603);
  for (size_t i = 0; i < n; ++i) { h ^= d[i]; h *= UINT64_C(1099511628211); }
  return h;
}

#define CORPUS_MAX 200
static double corpus[CORPUS_MAX][16];
static int corpus_rows = 0;
static char corpus_strings[64][64];
static int corpus_string_rows = 0;

static void load_corpus(void) {
  if (corpus_rows > 0) return;
  const char *directory = getenv("LDA_CAIRO_PATHDIR");
  if (!directory || !*directory) directory = "/opt/lda/fixtures/cairo-paths";
  char path[512];
  snprintf(path, sizeof path, "%s/paths.txt", directory);
  FILE *stream = fopen(path, "r");
  if (!stream) { fprintf(stderr, "open %s failed\n", path); exit(66); }
  while (corpus_rows < CORPUS_MAX) {
    int got = 0;
    for (int i = 0; i < 16; ++i)
      got += fscanf(stream, "%lf", &corpus[corpus_rows][i]);
    if (got != 16) break;
    corpus_rows++;
  }
  fclose(stream);
  snprintf(path, sizeof path, "%s/strings.txt", directory);
  stream = fopen(path, "r");
  if (!stream) { fprintf(stderr, "open %s failed\n", path); exit(66); }
  while (corpus_string_rows < 64 &&
         fgets(corpus_strings[corpus_string_rows], 64, stream)) {
    char *nl = strchr(corpus_strings[corpus_string_rows], '\n');
    if (nl) *nl = 0;
    if (corpus_strings[corpus_string_rows][0]) corpus_string_rows++;
  }
  fclose(stream);
  if (corpus_rows == 0 || corpus_string_rows == 0) {
    fprintf(stderr, "corpus is empty\n");
    exit(66);
  }
}

int main(int argc, char **argv) {
  if (argc < 3) return 64;
  void *so = dlopen("libcairo.so.2", RTLD_NOW);
  if (!so) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 69; }
  surface_create_fn image_create = (surface_create_fn)dlsym(so, "cairo_image_surface_create");
  from_png_fn from_png = (from_png_fn)dlsym(so, "cairo_image_surface_create_from_png");
  create_fn cr_create = (create_fn)dlsym(so, "cairo_create");
  void1_fn cr_destroy = (void1_fn)dlsym(so, "cairo_destroy");
  void1_fn surf_destroy = (void1_fn)dlsym(so, "cairo_surface_destroy");
  void1_fn surf_flush = (void1_fn)dlsym(so, "cairo_surface_flush");
  data_fn surf_data = (data_fn)dlsym(so, "cairo_image_surface_get_data");
  int1_fn surf_h = (int1_fn)dlsym(so, "cairo_image_surface_get_height");
  int1_fn surf_stride = (int1_fn)dlsym(so, "cairo_image_surface_get_stride");
  int1_fn surf_status = (int1_fn)dlsym(so, "cairo_surface_status");
  rgba_fn set_rgba = (rgba_fn)dlsym(so, "cairo_set_source_rgba");
  rect_fn rectangle = (rect_fn)dlsym(so, "cairo_rectangle");
  void1_fn fill = (void1_fn)dlsym(so, "cairo_fill");
  void1_fn paint = (void1_fn)dlsym(so, "cairo_paint");
  radial_fn radial = (radial_fn)dlsym(so, "cairo_pattern_create_radial");
  stop_fn add_stop = (stop_fn)dlsym(so, "cairo_pattern_add_color_stop_rgba");
  mask_fn mask = (mask_fn)dlsym(so, "cairo_mask");
  void1_fn pattern_destroy = (void1_fn)dlsym(so, "cairo_pattern_destroy");
  move_fn move_to = (move_fn)dlsym(so, "cairo_move_to");
  move_fn line_to = (move_fn)dlsym(so, "cairo_line_to");
  text_fn text_path = (text_fn)dlsym(so, "cairo_text_path");
  setsz_fn set_font_size = (setsz_fn)dlsym(so, "cairo_set_font_size");
  void1_fn stroke = (void1_fn)dlsym(so, "cairo_stroke");
  curve_fn curve_to = (curve_fn)dlsym(so, "cairo_curve_to");
  dash_fn set_dash = (dash_fn)dlsym(so, "cairo_set_dash");
  seti_fn set_line_cap = (seti_fn)dlsym(so, "cairo_set_line_cap");
  seti_fn set_line_join = (seti_fn)dlsym(so, "cairo_set_line_join");
  seti_fn set_fill_rule = (seti_fn)dlsym(so, "cairo_set_fill_rule");
  setd_fn set_line_width = (setd_fn)dlsym(so, "cairo_set_line_width");
  void1_fn new_path = (void1_fn)dlsym(so, "cairo_new_path");
  void1_fn close_path = (void1_fn)dlsym(so, "cairo_close_path");
  if (!image_create || !from_png || !cr_create || !cr_destroy || !surf_destroy ||
      !surf_flush || !surf_data || !surf_h || !surf_stride || !surf_status ||
      !set_rgba || !rectangle || !fill || !paint || !radial || !add_stop ||
      !mask || !pattern_destroy || !move_to || !line_to || !text_path ||
      !set_font_size || !stroke || !curve_to || !set_dash || !set_line_cap ||
      !set_line_join || !set_fill_rule || !set_line_width || !new_path ||
      !close_path) {
    fprintf(stderr, "dlsym: %s\n", dlerror());
    return 69;
  }
  const char *workload = argv[1];
  const int iterations = atoi(argv[2]);
  uint64_t agg = UINT64_C(1469598103934665603);
#define MIX(surface) do { \
    surf_flush(surface); \
    size_t n = (size_t)surf_h(surface) * (size_t)surf_stride(surface); \
    agg = agg * UINT64_C(1099511628211) ^ hash_bytes(surf_data(surface), n); \
  } while (0)

  if (!strcmp(workload, "stroke-dash") || !strcmp(workload, "fill-tess") ||
      !strcmp(workload, "text-corpus"))
    load_corpus();

  for (int it = 0; it < iterations; ++it) {
    if (!strcmp(workload, "png-load") || !strcmp(workload, "all")) {
      for (int i = 3; i < argc; ++i) {
        cptr s = from_png(argv[i]);
        if (!s || surf_status(s)) { fprintf(stderr, "png fail\n"); return 2; }
        MIX(s);
        surf_destroy(s);
      }
    }
    if (!strcmp(workload, "paint") || !strcmp(workload, "all")) {
      cptr s = image_create(0 /*ARGB32*/, 512, 512);
      cptr c = cr_create(s);
      for (int i = 0; i < 40; ++i) {
        set_rgba(c, (i * 37 % 255) / 255.0, (i * 91 % 255) / 255.0, (i * 53 % 255) / 255.0, 0.7);
        rectangle(c, (i * 13) % 300, (i * 29) % 300, 200, 200);
        fill(c);
      }
      MIX(s);
      cr_destroy(c); surf_destroy(s);
    }
    if (!strcmp(workload, "mask") || !strcmp(workload, "all")) {
      cptr s = image_create(0, 512, 512);
      cptr c = cr_create(s);
      cptr p = radial(256, 256, 20, 256, 256, 250);
      add_stop(p, 0.0, 1, 0.2, 0.1, 1.0);
      add_stop(p, 1.0, 0.1, 0.2, 1, 0.0);
      for (int i = 0; i < 12; ++i) { set_rgba(c, 0.3, 0.6, 0.9, 1.0); mask(c, p); }
      MIX(s);
      pattern_destroy(p); cr_destroy(c); surf_destroy(s);
    }
    if (!strcmp(workload, "text-path") || !strcmp(workload, "all")) {
      cptr s = image_create(0, 512, 256);
      cptr c = cr_create(s);
      set_font_size(c, 32.0);
      set_rgba(c, 0, 0, 0, 1);
      for (int i = 0; i < 12; ++i) {
        move_to(c, 8, 40 + (i * 17) % 180);
        text_path(c, "Ubuntu 26.04 LDA cairo bench 0123456789");
        stroke(c);
      }
      MIX(s);
      cr_destroy(c); surf_destroy(s);
    }
    if (!strcmp(workload, "stroke-dash")) {
      /* Dashed bezier stroking: cairo's own stroker, dash walker, and tor
       * scan converter dominate; pixman only receives the final spans. */
      cptr s = image_create(0, 512, 512);
      cptr c = cr_create(s);
      set_rgba(c, 0.1, 0.3, 0.8, 0.9);
      set_line_cap(c, 1 /*ROUND*/);
      set_line_join(c, 1 /*ROUND*/);
      for (int r = 0; r < corpus_rows; ++r) {
        const double *v = corpus[r];
        new_path(c);
        set_line_width(c, 2.0 + (r % 5));
        set_dash(c, v + 12, 4, (double)(r % 7));
        move_to(c, v[0] / 10.0, v[1] / 10.0);
        curve_to(c, v[2] / 10.0, v[3] / 10.0, v[4] / 10.0, v[5] / 10.0, v[6] / 10.0, v[7] / 10.0);
        curve_to(c, v[8] / 10.0, v[9] / 10.0, v[10] / 10.0, v[11] / 10.0, v[0] / 10.0, v[1] / 10.0);
        stroke(c);
      }
      MIX(s);
      cr_destroy(c); surf_destroy(s);
    }
    if (!strcmp(workload, "fill-tess")) {
      /* Self-intersecting polygon fills: cairo's tessellator and scan
       * converter carry the cost of resolving the winding structure. */
      cptr s = image_create(0, 512, 512);
      cptr c = cr_create(s);
      set_rgba(c, 0.8, 0.2, 0.1, 0.8);
      for (int r = 0; r < corpus_rows; ++r) {
        const double *v = corpus[r];
        new_path(c);
        set_fill_rule(c, r % 2 /*WINDING then EVEN_ODD*/);
        move_to(c, v[0] / 10.0, v[1] / 10.0);
        line_to(c, v[4] / 10.0, v[5] / 10.0);
        line_to(c, v[8] / 10.0, v[9] / 10.0);
        line_to(c, v[2] / 10.0, v[3] / 10.0);
        line_to(c, v[6] / 10.0, v[7] / 10.0);
        line_to(c, v[10] / 10.0, v[11] / 10.0);
        close_path(c);
        fill(c);
      }
      MIX(s);
      cr_destroy(c); surf_destroy(s);
    }
    if (!strcmp(workload, "text-corpus")) {
      cptr s = image_create(0, 512, 256);
      cptr c = cr_create(s);
      set_font_size(c, 30.0);
      set_rgba(c, 0, 0, 0, 1);
      for (int i = 0; i < corpus_string_rows; ++i) {
        move_to(c, 6, 36 + (i * 19) % 190);
        text_path(c, corpus_strings[i]);
        stroke(c);
      }
      MIX(s);
      cr_destroy(c); surf_destroy(s);
    }
  }
  printf("%016llx\n", (unsigned long long)agg);
  return 0;
}
C
  cc -O2 -Wall -Werror "$CAIRO_FIXDIR/cairo-ops.c" -o "$CAIRO_FIXDIR/cairo-ops" -ldl
  "$CAIRO_FIXDIR/cairo-ops" paint 1 >"$CAIRO_FIXDIR/selftest.txt"
}

lda_cairo_attribution() {
  local mode="${1:?mode required}"
  local libdir probe
  libdir="$(lda_pkg_libdir "$mode")"
  probe="$(mktemp)"
  lda_run_with_pkg "$mode" env LD_DEBUG=libs \
    "$CAIRO_FIXDIR/cairo-ops" paint 1 >/dev/null 2>"$probe"
  grep -F "$libdir/libcairo.so.2" "$probe" >/dev/null || {
    rm -f "$probe"
    echo "cairo-ops did not load $libdir/libcairo.so.2" >&2
    return 65
  }
  rm -f "$probe"
}
