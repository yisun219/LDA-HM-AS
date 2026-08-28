#!/usr/bin/env bash
# Install the soup card's runtime consumers from the pinned snapshot and
# write the loopback HTTP client/server fixtures.
set -euo pipefail
apt_root=/opt/lda/apt
sources="$apt_root/snapshot.sources"
test -s "$sources" || { echo "snapshot sources missing" >&2; exit 78; }
OPTS=(-o "Dir::Etc::sourcelist=$sources" -o "Dir::Etc::sourceparts=-"
      -o "Dir::State::lists=$apt_root/lists" -o "Dir::Cache=$apt_root/cache"
      -o "APT::Get::List-Cleanup=0" -o "Acquire::Check-Valid-Until=false")
sudo -n apt-get "${OPTS[@]}" install -y --allow-downgrades \
  libsoup-3.0-0 gir1.2-soup-3.0 python3-gi
mkdir -p /opt/lda/fixtures/soup
cat >/opt/lda/fixtures/soup/http-server.py <<'PYW'
from http.server import BaseHTTPRequestHandler, HTTPServer
PAYLOAD = (b"payload-" * 96)[:512]
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "max-age=60, public")
        self.send_header("X-Answer", self.path[-40:])
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()
        self.wfile.write(PAYLOAD)
    def log_message(self, *args):
        pass
server = HTTPServer(("127.0.0.1", 0), Handler)
print(server.server_port, flush=True)
server.serve_forever()
PYW
cat >/opt/lda/fixtures/soup/http-client.py <<'PYW'
import gi, sys, hashlib
gi.require_version("Soup", "3.0")
from gi.repository import Soup
base, count = sys.argv[1], int(sys.argv[2])
session = Soup.Session()
digest = hashlib.sha256()
for index in range(count):
    message = Soup.Message.new("GET", f"{base}/item/{index}")
    request_headers = message.get_request_headers()
    request_headers.append("X-Trace", f"probe-{index}")
    request_headers.append(
        "Accept", "text/plain, application/json;q=0.9, */*;q=0.1"
    )
    body = session.send_and_read(message, None)
    response_headers = message.get_response_headers()
    digest.update(bytes(body.get_data() or b""))
    digest.update(str(response_headers.get_one("Content-Type")).encode())
    digest.update(str(response_headers.get_one("X-Answer")).encode())
print(digest.hexdigest()[:16])
PYW
echo "soup workbench installed (libsoup runtime, gi bindings, loopback fixtures)"
