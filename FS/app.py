import ipaddress
import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

BIND_HOST = os.environ.get("FS_HOST", "0.0.0.0")
BIND_PORT = int(os.environ.get("FS_PORT", "9090"))
AS_TIMEOUT = float(os.environ.get("AS_TIMEOUT", "3"))


def fibonacci(number):
    if number < 1:
        raise ValueError("number must be a positive sequence number")
    previous, current = 0, 1
    for _ in range(number - 1):
        previous, current = current, previous + current
    return previous


class FileServer(BaseHTTPRequestHandler):
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

    def do_PUT(self):
        if urlsplit(self.path).path != "/register":
            self.send_body(404, "Not found\n")
            return

        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > 1024 * 1024:
                raise ValueError("Invalid request size")
            payload = json.loads(self.rfile.read(size).decode("utf-8"))
            hostname = str(payload["hostname"]).strip()
            ip = str(payload["ip"]).strip()
            as_ip = str(payload["as_ip"]).strip()
            as_port = int(payload["as_port"])
            ipaddress.ip_address(ip)
            if not hostname or any(character.isspace() for character in hostname):
                raise ValueError("Invalid hostname")
            if not 1 <= as_port <= 65535:
                raise ValueError("Invalid AS port")
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
            self.send_body(400, "Invalid registration request\n")
            return

        message = "TYPE=A\nNAME=%s\nVALUE=%s\nTTL=10\n" % (hostname, ip)
        try:
            targets = socket.getaddrinfo(as_ip, as_port, type=socket.SOCK_DGRAM)
            family, socktype, protocol, _, address = targets[0]
            with socket.socket(family, socktype, protocol) as udp_socket:
                udp_socket.settimeout(AS_TIMEOUT)
                udp_socket.sendto(message.encode("utf-8"), address)
                response, _ = udp_socket.recvfrom(4096)
            if response.decode("utf-8", errors="replace").strip() != "Success":
                self.send_body(500, "AS did not confirm the registration\n")
                return
        except (OSError, IndexError):
            self.send_body(500, "Could not complete registration with AS\n")
            return

        self.send_body(201, "Registered %s\n" % hostname)

    def do_GET(self):
        parsed = urlsplit(self.path)
        if parsed.path != "/fibonacci":
            self.send_body(404, "Not found\n")
            return

        parameters = parse_qs(parsed.query, keep_blank_values=True)
        raw_number = parameters.get("number", [""])[0]
        try:
            number = int(raw_number)
            if number < 1:
                raise ValueError("number must be a positive sequence number")
            result = fibonacci(number)
        except (TypeError, ValueError):
            self.send_body(400, "number must be a positive integer\n")
            return

        self.send_body(200, str(result) + "\n")

    def log_message(self, format_string, *args):
        print("%s - %s" % (self.client_address[0], format_string % args), flush=True)


if __name__ == "__main__":
    server = ThreadingHTTPServer((BIND_HOST, BIND_PORT), FileServer)
    print("FS listening on %s:%s" % (BIND_HOST, BIND_PORT), flush=True)
    server.serve_forever()
