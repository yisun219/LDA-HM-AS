#ifndef LDA_FIXTURE_H
#define LDA_FIXTURE_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

struct lda_fixture_state {
    uint64_t calls;
    uint32_t flags;
};

uint64_t lda_accumulate(uint32_t count);
const char *lda_fixture_version(void);

#ifdef __cplusplus
}
#endif

#endif
