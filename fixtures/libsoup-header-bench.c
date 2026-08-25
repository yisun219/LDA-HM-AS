#include <libsoup/soup.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static const char request[] =
    "GET /assets/app.js?build=2604 HTTP/1.1\r\n"
    "Host: example.test\r\n"
    "User-Agent: LDA-Benchmark/1.0\r\n"
    "Accept: text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8\r\n"
    "Accept-Language: en-US,en;q=0.9\r\n"
    "Accept-Encoding: gzip, deflate, br\r\n"
    "Cache-Control: no-cache\r\n"
    "Pragma: no-cache\r\n"
    "Connection: keep-alive\r\n"
    "Upgrade-Insecure-Requests: 1\r\n"
    "Sec-WebSocket-Version: 13\r\n"
    "Content-Type: application/json; charset=utf-8\r\n"
    "Content-Length: 128\r\n"
    "If-None-Match: W/\"abc123\"\r\n"
    "If-Modified-Since: Tue, 25 Aug 2026 10:00:00 GMT\r\n"
    "Origin: https://example.test\r\n"
    "Referer: https://example.test/index.html\r\n"
    "Cookie: session=abcdef; theme=dark\r\n"
    "X-Request-ID: 0123456789abcdef\r\n"
    "X-Forwarded-For: 192.0.2.1\r\n\r\n";

static uint64_t now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

int main(int argc, char **argv) {
    long loops = argc > 1 ? strtol(argv[1], NULL, 10) : 10000;
    unsigned long checksum = 0;
    for (int warmup = 0; warmup < 1000; ++warmup) {
        SoupMessageHeaders *headers = soup_message_headers_new(SOUP_MESSAGE_HEADERS_REQUEST);
        checksum += soup_headers_parse_request(request, (int)sizeof(request) - 1, headers, NULL, NULL, NULL);
        soup_message_headers_unref(headers);
    }
    uint64_t start = now_ns();
    for (long i = 0; i < loops; ++i) {
        SoupMessageHeaders *headers = soup_message_headers_new(SOUP_MESSAGE_HEADERS_REQUEST);
        checksum += soup_headers_parse_request(request, (int)sizeof(request) - 1, headers, NULL, NULL, NULL);
        checksum += (uintptr_t)soup_message_headers_get_one(headers, "Content-Type") & 1u;
        soup_message_headers_unref(headers);
    }
    double seconds = (double)(now_ns() - start) / 1000000000.0;
    printf("%.9f %lu\n", seconds, checksum);
    return checksum ? 0 : 1;
}
