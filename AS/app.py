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
    for row in line.splitlines():
        for item in row.split():
            key, separator, value = item.partition("=")
            if separator:
                result[key] = value
    return result


class NameServer(socketserver.BaseRequestHandler):
    def handle(self):
        packet, udp_socket = self.request
        message = packet.decode("utf-8", errors="replace")
        fields = parse_fields(message)
        if fields.get("TYPE") != "A":
            udp_socket.sendto(b"ERROR=BAD_REQUEST\n", self.client_address)
            return

        hostname = fields.get("NAME", "")
        if not hostname:
            udp_socket.sendto(b"ERROR=BAD_REQUEST\n", self.client_address)
            return



        if "VALUE" in fields or "TTL" in fields:
            value = fields.get("VALUE", "")
            raw_ttl = fields.get("TTL", "")
            if not value or not raw_ttl:
                udp_socket.sendto(b"ERROR=BAD_REQUEST\n", self.client_address)
                return
            try:
                ttl = int(raw_ttl)
                if ttl < 0:
                    raise ValueError("TTL must be nonnegative")
            except ValueError:
                udp_socket.sendto(b"ERROR=BAD_REQUEST\n", self.client_address)
                return
            try:
                with LOCK:
                    records = load_records()
                    records[hostname] = {"ip": value, "ttl": ttl}
                    save_records(records)
            except OSError:
                udp_socket.sendto(b"ERROR=REGISTRATION_FAILED\n", self.client_address)
                return
            print("Registered %s -> %s" % (hostname, value), flush=True)
            udp_socket.sendto(b"Success", self.client_address)
            return

        with LOCK:
            record = load_records().get(hostname)

        if not record:
            udp_socket.sendto(b"ERROR=NOT_FOUND\n", self.client_address)
            return

        reply = "TYPE=A\nNAME=%s\nVALUE=%s\nTTL=%s\n" % (
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
