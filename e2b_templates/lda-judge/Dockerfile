FROM ubuntu:26.04
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 ca-certificates pkg-config abi-compliance-checker binutils dpkg-dev \
    gcc libc6-dev libcairo2 libcairo2-dev libsoup-3.0-0 libsoup-3.0-dev \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /opt/lda/judge \
    && printf %s 'I2luY2x1ZGUgPGRsZmNuLmg+CiNpbmNsdWRlIDxzdGRpby5oPgoKaW50IG1haW4oaW50IGFyZ2MsIGNoYXIgKiphcmd2KSB7CiAgICBpZiAoYXJnYyAhPSAzKSB7CiAgICAgICAgcmV0dXJuIDY0OwogICAgfQogICAgdm9pZCAqbGlicmFyeSA9IGRsb3Blbihhcmd2WzFdLCBSVExEX05PVyB8IFJUTERfTE9DQUwpOwogICAgaWYgKGxpYnJhcnkgPT0gTlVMTCkgewogICAgICAgIHJldHVybiA2NTsKICAgIH0KICAgIHZvaWQgKnN5bWJvbCA9IGRsc3ltKGxpYnJhcnksIGFyZ3ZbMl0pOwogICAgaWYgKHN5bWJvbCA9PSBOVUxMKSB7CiAgICAgICAgZGxjbG9zZShsaWJyYXJ5KTsKICAgICAgICByZXR1cm4gNjY7CiAgICB9CiAgICBwcmludGYoImRsb3Blbi9kbHN5bSBva1xuIik7CiAgICBkbGNsb3NlKGxpYnJhcnkpOwogICAgcmV0dXJuIDA7Cn0K' | base64 -d > /opt/lda/judge/ffi_smoke.c
RUN gcc -O2 -Wall -Wextra /opt/lda/judge/ffi_smoke.c -ldl -o /opt/lda/judge/ffi_smoke \
    && chmod 0555 /opt/lda/judge/ffi_smoke
COPY manifest.json /opt/lda/template-manifest.json
WORKDIR /workspace
