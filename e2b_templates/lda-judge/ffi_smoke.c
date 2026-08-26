#include <dlfcn.h>
#include <stdio.h>

int main(int argc, char **argv) {
    if (argc != 3) {
        return 64;
    }
    void *library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (library == NULL) {
        return 65;
    }
    void *symbol = dlsym(library, argv[2]);
    if (symbol == NULL) {
        dlclose(library);
        return 66;
    }
    printf("dlopen/dlsym ok\n");
    dlclose(library);
    return 0;
}
