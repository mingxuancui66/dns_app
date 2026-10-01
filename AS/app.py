import json
import os
import socketserver
import threading
from pathlib import Path

BIND_HOST = os.environ.get("AS_HOST", "0.0.0.0")
BIND_PORT = int(os.environ.get("AS_PORT", "53533"))
DATA_FILE = Path(os.environ.get("AS_DATA_FILE", "/data/records.json"))
LOCK = threading.Lock()


def load_records():
    try:
        with DATA_FILE.open("r", encoding="utf-8") as source:
            records = json.load(source)
        return records if isinstance(records, dict) else {}
    except (OSError, ValueError):
        return {}


def save_records(records):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = DATA_FILE.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as target:
        json.dump(records, target, indent=2, sort_keys=True)
        target.write("\n")
    os.replace(str(temporary), str(DATA_FILE))


def parse_fields(line):
    result = {}
    for item in line.split():
        key, separator, value = item.partition("=")
        if separator:
            result[key] = value
    return result


class NameServer(socketserver.BaseRequestHandler):
    def handle(self):
        packet, udp_socket = self.request
        message = packet.decode("utf-8", errors="replace")
        lines = [line.strip() for line in message.splitlines() if line.strip()]

        if not lines or lines[0] != "TYPE=A" or len(lines) < 2:
            udp_socket.sendto(b"ERROR=BAD_REQUEST\n", self.client_address)
            return

        fields = parse_fields(lines[1])
        hostname = fields.get("NAME", "")
        if not hostname:
            udp_socket.sendto(b"ERROR=BAD_REQUEST\n", self.client_address)
            return

        # A registration includes VALUE and TTL. A lookup contains only NAME.
        if "VALUE" in fields:
            value = fields["VALUE"]
            if not value or not fields.get("TTL", ""):
                return
            try:
                ttl = int(fields["TTL"])
            except ValueError:
                return
            with LOCK:
                records = load_records()
                records[hostname] = {"ip": value, "ttl": ttl}
                save_records(records)
            print("Registered %s -> %s" % (hostname, value), flush=True)
            return

        with LOCK:
            record = load_records().get(hostname)

        if not record:
            udp_socket.sendto(b"ERROR=NOT_FOUND\n", self.client_address)
            return

        reply = "TYPE=A\nNAME=%s VALUE=%s TTL=%s\n" % (
            hostname,
            record["ip"],
            record.get("ttl", 10),
        )
        udp_socket.sendto(reply.encode("utf-8"), self.client_address)


class ThreadedUDPServer(socketserver.ThreadingUDPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    with ThreadedUDPServer((BIND_HOST, BIND_PORT), NameServer) as server:
        print("AS listening on %s:%s" % (BIND_HOST, BIND_PORT), flush=True)
        server.serve_forever()
