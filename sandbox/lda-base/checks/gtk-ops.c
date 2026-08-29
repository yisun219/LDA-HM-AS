/* gtk-ops: deterministic GTK workloads through the SELECTED libgtk, dlopen'd
 * so no -dev package is required and LD_LIBRARY_PATH alone picks baseline or
 * candidate. Workloads concentrate cycles in gtk's own machinery (CSS parse,
 * selector match / style resolution, layout measure) rather than in pango
 * text shaping or a language binding.
 *
 * usage: gtk-ops <3|4> <css-parse|style-match|layout|all> <iterations> <fixdir>
 * <fixdir> holds corpus.css and tree-seed.txt (train or hidden holdout set).
 * Prints one FNV chain hash as the last line.
 */
#include <dlfcn.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef void *p;
typedef struct { float r, g, b, a; } RGBA4;
typedef struct { double r, g, b, a; } RGBA3;

#define MAX_WIDGETS 1400

static uint64_t agg = UINT64_C(1469598103934665603);
static void mixb(const void *d, size_t n) {
  const unsigned char *s = d;
  for (size_t i = 0; i < n; ++i) { agg ^= s[i]; agg *= UINT64_C(1099511628211); }
}
static void mixi(long v) { mixb(&v, sizeof v); }

static void *need(void *so, const char *name) {
  void *sym = dlsym(so, name);
  if (!sym) { fprintf(stderr, "dlsym %s: %s\n", name, dlerror()); exit(69); }
  return sym;
}

static char *read_file(const char *path) {
  FILE *stream = fopen(path, "rb");
  if (!stream) { fprintf(stderr, "open %s failed\n", path); exit(66); }
  fseek(stream, 0, SEEK_END);
  long size = ftell(stream);
  fseek(stream, 0, SEEK_SET);
  char *buffer = malloc((size_t)size + 1);
  if (fread(buffer, 1, (size_t)size, stream) != (size_t)size) exit(66);
  buffer[size] = 0;
  fclose(stream);
  return buffer;
}

int main(int argc, char **argv) {
  if (argc < 5) return 64;
  const int major = atoi(argv[1]);
  const char *workload = argv[2];
  const int iterations = atoi(argv[3]);
  const char *fixdir = argv[4];
  char path[512];
  snprintf(path, sizeof path, "%s/corpus.css", fixdir);
  char *css = read_file(path);
  snprintf(path, sizeof path, "%s/tree-seed.txt", fixdir);
  char *seed_text = read_file(path);
  const unsigned seed = (unsigned)strtoul(seed_text, NULL, 10);
  free(seed_text);

  const char *soname = major == 4 ? "libgtk-4.so.1" : "libgtk-3.so.0";
  void *so = dlopen(soname, RTLD_NOW | RTLD_GLOBAL);
  if (!so) { fprintf(stderr, "dlopen: %s\n", dlerror()); return 69; }

  p (*css_new)(void) = (p (*)(void))need(so, "gtk_css_provider_new");
  char *(*css_str)(p) = (char *(*)(p))need(so, "gtk_css_provider_to_string");
  void (*css_load_string)(p, const char *) =
      (void (*)(p, const char *))dlsym(so, "gtk_css_provider_load_from_string");
  void *css_load_data = dlsym(so, "gtk_css_provider_load_from_data");
  void (*load_css3)(p, const char *, long, p) = (void (*)(p, const char *, long, p))css_load_data;
  void (*load_css4)(p, const char *, long) = (void (*)(p, const char *, long))css_load_data;
  p (*box_new)(int, int) = (p (*)(int, int))need(so, "gtk_box_new");
  p (*frame_new)(const char *) = (p (*)(const char *))need(so, "gtk_frame_new");
  p (*sep_new)(int) = (p (*)(int))need(so, "gtk_separator_new");
  void (*set_size_request)(p, int, int) =
      (void (*)(p, int, int))need(so, "gtk_widget_set_size_request");
  void (*realize)(p) = (void (*)(p))need(so, "gtk_widget_realize");
  void (*obj_unref)(p) = (void (*)(p))need(so, "g_object_unref");

  p widgets[MAX_WIDGETS];
  int count = 0;
  #define KEEP(w) do { if (count < MAX_WIDGETS) widgets[count++] = (w); } while (0)

  void (*add_class4)(p, const char *) = (void (*)(p, const char *))dlsym(so, "gtk_widget_add_css_class");
  void (*remove_class4)(p, const char *) = (void (*)(p, const char *))dlsym(so, "gtk_widget_remove_css_class");
  void (*get_color4)(p, RGBA4 *) = (void (*)(p, RGBA4 *))dlsym(so, "gtk_widget_get_color");
  p (*get_ctx)(p) = (p (*)(p))dlsym(so, "gtk_widget_get_style_context");
  void (*ctx_add_class)(p, const char *) = (void (*)(p, const char *))dlsym(so, "gtk_style_context_add_class");
  void (*ctx_remove_class)(p, const char *) = (void (*)(p, const char *))dlsym(so, "gtk_style_context_remove_class");
  void (*ctx_get_color)(p, int, RGBA3 *) = (void (*)(p, int, RGBA3 *))dlsym(so, "gtk_style_context_get_color");

  p window, root;
  if (major == 4) {
    int (*init_check)(void) = (int (*)(void))need(so, "gtk_init_check");
    if (!init_check()) { fprintf(stderr, "gtk4 init failed\n"); return 69; }
    p (*window_new)(void) = (p (*)(void))need(so, "gtk_window_new");
    void (*window_set_child)(p, p) = (void (*)(p, p))need(so, "gtk_window_set_child");
    void (*box_append)(p, p) = (void (*)(p, p))need(so, "gtk_box_append");
    void (*frame_set_child)(p, p) = (void (*)(p, p))need(so, "gtk_frame_set_child");
    window = window_new();
    root = box_new(1 /*vertical*/, 2);
    window_set_child(window, root);
    KEEP(root);
    for (int i = 0; i < 240; ++i) {
      p row = box_new(0, 1);
      p frame = frame_new(NULL);
      p inner = box_new(0, 1);
      for (int j = 0; j < 3; ++j) { p sep = sep_new(j % 2); box_append(inner, sep); KEEP(sep); }
      frame_set_child(frame, inner);
      box_append(row, frame);
      box_append(root, row);
      KEEP(row); KEEP(frame); KEEP(inner);
      char cls[16];
      snprintf(cls, sizeof cls, "k%u", (i * seed) % 97u);
      add_class4(row, cls);
      snprintf(cls, sizeof cls, "m%u", (i + seed) % 89u);
      add_class4(frame, cls);
    }
  } else {
    int zero = 0; char **none = NULL;
    int (*init_check)(int *, char ***) = (int (*)(int *, char ***))need(so, "gtk_init_check");
    if (!init_check(&zero, &none)) { fprintf(stderr, "gtk3 init failed\n"); return 69; }
    p (*window_new)(int) = (p (*)(int))need(so, "gtk_window_new");
    void (*container_add)(p, p) = (void (*)(p, p))need(so, "gtk_container_add");
    void (*show_all)(p) = (void (*)(p))need(so, "gtk_widget_show_all");
    window = window_new(0 /*TOPLEVEL*/);
    root = box_new(1, 2);
    container_add(window, root);
    KEEP(root);
    for (int i = 0; i < 240; ++i) {
      p row = box_new(0, 1);
      p frame = frame_new(NULL);
      p inner = box_new(0, 1);
      for (int j = 0; j < 3; ++j) { p sep = sep_new(j % 2); container_add(inner, sep); KEEP(sep); }
      container_add(frame, inner);
      container_add(row, frame);
      container_add(root, row);
      KEEP(row); KEEP(frame); KEEP(inner);
      char cls[16];
      snprintf(cls, sizeof cls, "k%u", (i * seed) % 97u);
      ctx_add_class(get_ctx(row), cls);
      snprintf(cls, sizeof cls, "m%u", (i + seed) % 89u);
      ctx_add_class(get_ctx(frame), cls);
    }
    show_all(root);
  }
  realize(window);

  p provider = css_new();
  if (major == 4 && css_load_string) css_load_string(provider, css);
  else if (major == 4) load_css4(provider, css, -1);
  else load_css3(provider, css, -1, NULL);
  if (major == 4) {
    p (*display_default)(void) = (p (*)(void))need(so, "gdk_display_get_default");
    void (*add_for_display)(p, p, unsigned) =
        (void (*)(p, p, unsigned))need(so, "gtk_style_context_add_provider_for_display");
    add_for_display(display_default(), provider, 800);
  } else {
    p (*screen_default)(void) = (p (*)(void))need(so, "gdk_screen_get_default");
    void (*add_for_screen)(p, p, unsigned) =
        (void (*)(p, p, unsigned))need(so, "gtk_style_context_add_provider_for_screen");
    add_for_screen(screen_default(), provider, 800);
  }

  for (int it = 0; it < iterations; ++it) {
    if (!strcmp(workload, "css-parse") || !strcmp(workload, "all")) {
      p fresh = css_new();
      if (major == 4 && css_load_string) css_load_string(fresh, css);
      else if (major == 4) load_css4(fresh, css, -1);
      else load_css3(fresh, css, -1, NULL);
      if (it == 0) {
        char *serialized = css_str(fresh);
        mixb(serialized, strlen(serialized));
        free(serialized);
      }
      obj_unref(fresh);
    }
    if (!strcmp(workload, "style-match") || !strcmp(workload, "all")) {
      /* Paired add/remove of the SAME class name keeps the class list
       * bounded, so per-iteration cost stays flat instead of accumulating. */
      char cls[16];
      const unsigned pair = (unsigned)(it % 2 ? it - 1 : (it >= 2 ? it - 2 : 0));
      snprintf(cls, sizeof cls, "k%u", (pair + seed) % 97u);
      for (int i = 0; i < count; ++i) {
        if (major == 4) {
          if (it % 2) add_class4(widgets[i], cls);
          else if (it >= 2) remove_class4(widgets[i], cls);
        } else {
          p ctx = get_ctx(widgets[i]);
          if (it % 2) ctx_add_class(ctx, cls);
          else if (it >= 2) ctx_remove_class(ctx, cls);
        }
      }
      for (int i = 0; i < count; ++i) {
        if (major == 4) {
          RGBA4 color; get_color4(widgets[i], &color);
          mixb(&color, sizeof color);
        } else {
          RGBA3 color; ctx_get_color(get_ctx(widgets[i]), 0, &color);
          mixb(&color, sizeof color);
        }
      }
    }
    if (!strcmp(workload, "layout") || !strcmp(workload, "all")) {
      /* Invalidate the size-request cache across the whole tree, so every
       * iteration is a real full-tree measure, not one cached root probe. */
      for (int i = 0; i < count; ++i)
        set_size_request(widgets[i], ((unsigned)(it + i) % 5u) ? -1 : 12, -1);
      set_size_request(root, 200 + (int)((it + seed) % 7u) * 40, -1);
      if (major == 4) {
        void (*measure)(p, int, int, int *, int *, int *, int *) =
            (void (*)(p, int, int, int *, int *, int *, int *))need(so, "gtk_widget_measure");
        int minimum, natural, b1, b2;
        measure(root, 1, 200 + (int)((it + seed) % 5u) * 60, &minimum, &natural, &b1, &b2);
        mixi(minimum); mixi(natural);
      } else {
        void (*preferred_h)(p, int, int *, int *) =
            (void (*)(p, int, int *, int *))need(so, "gtk_widget_get_preferred_height_for_width");
        int minimum, natural;
        preferred_h(root, 200 + (int)((it + seed) % 5u) * 60, &minimum, &natural);
        mixi(minimum); mixi(natural);
      }
    }
  }
  free(css);
  printf("%016llx\n", (unsigned long long)agg);
  return 0;
}
