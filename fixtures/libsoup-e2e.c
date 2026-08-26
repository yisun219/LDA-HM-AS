#include <libsoup/soup.h>
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
    unsigned long loops = argc > 1 ? strtoul(argv[1], NULL, 10) : 10;
    const char *url = argc > 2 ? argv[2] : "http://127.0.0.1:18080/payload";
    SoupSession *session = soup_session_new();
    for (unsigned long index = 0; index < loops; index++) {
        SoupMessage *message = soup_message_new("GET", url);
        GError *error = NULL;
        GBytes *body = soup_session_send_and_read(session, message, NULL, &error);
        if (error != NULL || body == NULL || soup_message_get_status(message) != SOUP_STATUS_OK) {
            if (error != NULL) g_error_free(error);
            if (body != NULL) g_bytes_unref(body);
            g_object_unref(message);
            g_object_unref(session);
            return 1;
        }
        g_bytes_unref(body);
        g_object_unref(message);
    }
    g_object_unref(session);
    puts("ok");
    return 0;
}
