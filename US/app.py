import os
import socket
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

BIND_HOST = os.environ.get("US_HOST", "0.0.0.0")
BIND_PORT = int(os.environ.get("US_PORT", "8080"))
NETWORK_TIMEOUT = float(os.environ.get("NETWORK_TIMEOUT", "3"))


def find_record(as_ip, as_port, hostname):
    query = "TYPE=A\nNAME=%s\n" % hostname
    targets = socket.getaddrinfo(as_ip, as_port, type=socket.SOCK_DGRAM)
    family, socktype, protocol, _, address = targets[0]
    with socket.socket(family, socktype, protocol) as udp_socket:
        udp_socket.settimeout(NETWORK_TIMEOUT)
        udp_socket.sendto(query.encode("utf-8"), address)
        response, _ = udp_socket.recvfrom(4096)

    text = response.decode("utf-8", errors="replace")
    fields = {}
    for line in text.splitlines():
        for item in line.split():
            key, separator, value = item.partition("=")
            if separator:
                fields[key] = value
    if fields.get("TYPE") == "A" and fields.get("NAME") == hostname and fields.get("VALUE"):
        return fields["VALUE"]
    raise LookupError(text.strip() or "AS returned an empty response")


def valid_port(value):
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError("port out of range")
    return port


class UserServer(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def send_body(self, status, body, content_type="text/plain; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)
        self.close_connection = True

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path != "/fibonacci":
            self.send_body(404, "Not found\n")
            return

        parameters = parse_qs(parsed.query, keep_blank_values=True)
        required = ("hostname", "fs_port", "number", "as_ip", "as_port")
        if any(not parameters.get(key) or not parameters[key][0] for key in required):
            self.send_body(400, "Required parameters: hostname, fs_port, number, as_ip, as_port\n")
            return

        hostname = parameters["hostname"][0]
        raw_number = parameters["number"][0]
        try:
            fs_port = valid_port(parameters["fs_port"][0])
            as_port = valid_port(parameters["as_port"][0])
        except ValueError:
            self.send_body(400, "fs_port and as_port must be valid port numbers\n")
            return

        try:
            fs_ip = find_record(parameters["as_ip"][0], as_port, hostname)
        except (OSError, IndexError, LookupError) as error:
            self.send_body(502, "AS lookup failed: %s\n" % error)
            return

        host_for_url = "[%s]" % fs_ip if ":" in fs_ip and not fs_ip.startswith("[") else fs_ip
        query = urllib.parse.urlencode({"number": raw_number})
        url = "http://%s:%s/fibonacci?%s" % (host_for_url, fs_port, query)
        request = urllib.request.Request(url, headers={"Connection": "close"})

        try:
            with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT) as response:
                self.send_body(response.status, response.read())
        except urllib.error.HTTPError as error:
            self.send_body(error.code, error.read())
        except (OSError, urllib.error.URLError, ValueError) as error:
            self.send_body(502, "FS request failed: %s\n" % error)

    def log_message(self, format_string, *args):
        print("%s - %s" % (self.client_address[0], format_string % args), flush=True)


if __name__ == "__main__":
    server = ThreadingHTTPServer((BIND_HOST, BIND_PORT), UserServer)
    print("US listening on %s:%s" % (BIND_HOST, BIND_PORT), flush=True)
    server.serve_forever()
