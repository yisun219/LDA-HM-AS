#include "lda_fixture.h"

#include <assert.h>
#include <string.h>

int main(void) {
    assert(lda_accumulate(0) == 0);
    assert(lda_accumulate(10) == 55);
    assert(strcmp(lda_fixture_version(), "1.0") == 0);
    return 0;
}
