#include <libaio.h>
int main(void) { io_context_t context = 0; return io_queue_init(1, &context); }
