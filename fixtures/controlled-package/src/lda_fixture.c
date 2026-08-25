#include "lda_fixture.h"

uint64_t lda_accumulate(uint32_t count) {
    uint64_t result = 0;
    for (uint32_t value = 0; value <= count; ++value) {
        result += value;
    }
    return result;
}

const char *lda_fixture_version(void) {
    return "1.0";
}
