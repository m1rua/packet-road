"""Bounded diagnostics. All sockets use one validated, pinned destination address."""
import ipaddress
import json
import logging
import re
import socket
import ssl
import subprocess
import time

import dns.resolver

LOG = logging.getLogger(__name__)


class PolicyError(ValueError):
    pass


def normalize_target(value: str) -> str:
    value = value.strip().rstrip(".")
    if not value or len(value) > 253 or "%" in value:
        raise PolicyError("Expected a domain or IP, without URL, path or port")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    try:
        value = value.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise PolicyError("Invalid domain") from exc
    if len(value) > 253 or not all(
        re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in value.split(".")
    ):
        raise PolicyError("Invalid domain; URLs, ports and shell syntax are unsupported")
    return value


def resolve(target: str) -> list[str]:
    try:
        return [str(ipaddress.ip_address(target))]
    except ValueError:
        pass
    resolver = dns.resolver.Resolver()
    resolver.timeout = 1
    resolver.lifetime = 2
    addresses = []
    failures = []
    for kind in ("A", "AAAA"):
        try:
            addresses.extend(str(answer) for answer in resolver.resolve(target, kind))
        except dns.exception.DNSException as exc:
            failures.append(exc)
    if not addresses:
        raise ValueError("DNS returned no addresses: " + "; ".join(str(e) for e in failures))
    return list(dict.fromkeys(addresses))


def validate_addresses(addresses: list[str], allow_private: bool = False) -> None:
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not allow_private and (not ip.is_global or ip.is_multicast
                                  or getattr(ip, "ipv4_mapped", None) is not None):
            raise PolicyError("Non-public destination rejected")


def command(argv: list[str], timeout: float = 3) -> str:
    completed = subprocess.run(
        argv, capture_output=True, text=True, timeout=timeout, check=True,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LC_ALL": "C"},
    )
    return completed.stdout


def route(address: str) -> dict:
    family = "-6" if ":" in address else "-4"
    data = json.loads(command(["ip", "-j", family, "route", "get", address]))[0]
    gateway = data.get("gateway")
    result = {"interface": data.get("dev"), "source_ip": data.get("prefsrc", data.get("src")),
              "gateway": gateway, "gateway_mac": None}
    if gateway:
        try:
            neighbors = json.loads(command(
                ["ip", "-j", family, "neigh", "show", "to", gateway, "dev", data["dev"]]
            ))
            result["gateway_mac"] = next(
                (entry.get("lladdr") for entry in neighbors if entry.get("lladdr")), None
            )
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    return result


def trace(address: str, max_hops: int) -> dict:
    argv = ["traceroute", "-6" if ":" in address else "-4", "-n", "-q", "1",
            "-w", "0.3", "-m", str(max_hops), address]
    raw = command(argv, timeout=8)
    hops = []
    for line in raw.splitlines():
        match = re.match(r"\s*(\d+)\s+(.+)", line)
        if match:
            details = match[2]
            rtt = re.search(r"([\d.]+)\s+ms", details)
            hops.append({"ttl": int(match[1]), "address": None if "*" in details
                         else details.split()[0], "rtt_ms": float(rtt[1]) if rtt else None,
                         "reply": details})
    return {"method": "UDP", "hops": hops, "raw": raw,
            "reached": bool(hops and hops[-1]["address"] == address)}


def connect(address: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET6 if ":" in address else socket.AF_INET)
    sock.settimeout(2)
    try:
        sock.connect((address, port))
        return sock
    except Exception:
        sock.close()
        raise


def tcp(address: str, port: int) -> dict:
    start = time.perf_counter()
    with connect(address, port):
        return {"connected": True, "connect_ms": (time.perf_counter() - start) * 1000}


def tls_probe(address: str, target: str, port: int) -> dict:
    start = time.perf_counter()
    with connect(address, port) as raw:
        with ssl.create_default_context().wrap_socket(raw, server_hostname=target) as sock:
            return {"version": sock.version(), "cipher": sock.cipher(),
                    "certificate": sock.getpeercert(),
                    "connect_and_tls_ms": (time.perf_counter() - start) * 1000}


def http_probe(address: str, target: str, port: int) -> dict:
    start = time.perf_counter()
    with connect(address, port) as raw:
        transport = ssl.create_default_context().wrap_socket(
            raw, server_hostname=target) if port != 80 else raw
        with transport as sock:
            connected = time.perf_counter()
            host = f"[{target}]" if ":" in target else target
            if port not in (80, 443):
                host += f":{port}"
            sock.sendall(f"HEAD / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n"
                         "User-Agent: packet-road/0.2\r\n\r\n".encode("ascii"))
            response = bytearray()
            deadline = time.monotonic() + 2
            first_byte_ms = None
            while b"\r\n\r\n" not in response and len(response) < 16384:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("HTTP header deadline exceeded")
                sock.settimeout(remaining)
                chunk = sock.recv(min(4096, 16384 - len(response)))
                if not chunk:
                    break
                if first_byte_ms is None:
                    first_byte_ms = (time.perf_counter() - connected) * 1000
                response.extend(chunk)
            if b"\r\n\r\n" not in response:
                raise ValueError("Incomplete HTTP headers or header exceeds 16 KiB")
            first = bytes(response).split(b"\r\n", 1)[0].decode("ascii", "replace")
            if not re.fullmatch(r"HTTP/1\.[01] [1-5][0-9]{2}(?: .*)?", first):
                raise ValueError("Invalid HTTP/1.x status line")
            return {"status_line": first, "status_code": int(first.split()[1]),
                    "connect_and_tls_ms": (connected - start) * 1000,
                    "first_byte_ms": first_byte_ms,
                    "headers_ms": (time.perf_counter() - connected) * 1000,
                    "redirect_followed": False}


def diagnose(target: str, port: int = 443, max_hops: int = 16,
             allow_private: bool = False) -> dict:
    target = normalize_target(target)
    if not 1 <= port <= 65535 or not 1 <= max_hops <= 20:
        raise PolicyError("Port must be 1..65535 and max_hops 1..20")
    result = {"target": target, "port": port, "observer": "process network namespace",
              "stages": {}}

    def stage(name, operation):
        start = time.perf_counter()
        try:
            data = operation()
            result["stages"][name] = {"status": "ok", "data": data}
            return data
        except PolicyError:
            raise
        except Exception as exc:
            LOG.info("stage=%s error_type=%s", name, type(exc).__name__)
            result["stages"][name] = {"status": "error", "error": str(exc)[:500],
                                      "error_type": type(exc).__name__}
            return None
        finally:
            if name in result["stages"]:
                result["stages"][name]["duration_seconds"] = time.perf_counter() - start

    addresses = stage("dns", lambda: resolve(target))
    if not addresses:
        return result
    validate_addresses(addresses, allow_private)
    address = addresses[0]
    result["selected_ip"] = address
    stage("route", lambda: route(address))
    stage("traceroute", lambda: trace(address, max_hops))
    stage("tcp", lambda: tcp(address, port))
    if port != 80:
        stage("tls", lambda: tls_probe(address, target, port))
    stage("http", lambda: http_probe(address, target, port))
    return result
