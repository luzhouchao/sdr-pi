#!/usr/bin/env python3
"""Submit a bounded RF-v1 metadata derivation to the existing local corpus API.

No IQ, model or dataset is read by this client. The service verifies the existing
parent package and creates a new record; it never overwrites the parent.
"""
import argparse
import ipaddress
import json
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

MAX_BYTES = 384 * 1024


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def endpoint(value):
    parsed = urllib.parse.urlsplit(value)
    if (parsed.scheme != "http" or parsed.username or parsed.password or parsed.query
            or parsed.fragment or parsed.path not in ("", "/")
            or not ipaddress.ip_address(parsed.hostname or "").is_loopback):
        raise ValueError("endpoint must be an explicit HTTP loopback IP and port")
    if parsed.port is None:
        raise ValueError("endpoint requires a port")
    return value.rstrip("/")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("corpus API redirects are forbidden")


def submit(base, parent, request_path):
    if not parent or len(parent) > 96 or not parent[0].isalnum() or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in parent):
        raise ValueError("invalid parent result ID")
    with request_path.open("rb") as stream:
        body = stream.read(MAX_BYTES + 1)
    if not body or len(body) > MAX_BYTES:
        raise ValueError("request must contain at most 384 KiB")
    value = json.loads(body, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("expected RF-v1 derive request v1")
    url = endpoint(base) + "/api/corpus/" + parent + "/derive-rf-v1"
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=10) as response:
        payload = response.read(MAX_BYTES + 1)
        if len(payload) > MAX_BYTES or response.status != 201:
            raise ValueError("invalid or oversized corpus response")
        result = json.loads(payload)
    # Emit only searchable metadata; evidence and IQ stay in the application store.
    return result["summary"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default="http://127.0.0.1:8787")
    parser.add_argument("--parent-result", required=True)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(submit(args.endpoint, args.parent_result, args.request), sort_keys=True))
    except (OSError, ValueError, KeyError, urllib.error.URLError) as error:
        parser.exit(1, f"import_failed: {error}\n")


if __name__ == "__main__":
    main()
