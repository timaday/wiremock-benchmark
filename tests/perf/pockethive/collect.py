"""Drain one explicitly selected benchmark Redis result list to a JSONL artifact."""

import argparse
import gzip
import json
import socket
import time
from pathlib import Path


def receive(stream):
    line = stream.readline()
    if not line.endswith(b'\r\n'):
        raise RuntimeError('Truncated Redis reply')
    kind, value = line[:1], line[1:-2]
    if kind == b'-':
        raise RuntimeError(value.decode())
    if kind == b':':
        return int(value)
    if kind == b'+':
        return value
    if kind == b'*':
        return None if int(value) == -1 else [receive(stream) for _ in range(int(value))]
    if kind == b'$':
        size = int(value)
        if size == -1:
            return None
        data = stream.read(size)
        if len(data) != size or stream.read(2) != b'\r\n':
            raise RuntimeError('Truncated Redis bulk value')
        return data
    raise RuntimeError('Unexpected Redis reply type')


def command(connection, stream, *parts):
    encoded = [str(part).encode() for part in parts]
    request = b'*' + str(len(encoded)).encode() + b'\r\n'
    request += b''.join(b'$' + str(len(part)).encode() + b'\r\n' + part + b'\r\n' for part in encoded)
    connection.sendall(request)
    return receive(stream)


def collect(args):
    key = 'wmb.' + args.run_id
    started = time.monotonic()
    seen = set()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with socket.create_connection((args.host, args.port), timeout=5) as connection:
        stream = connection.makefile('rb')
        opener = gzip.open if args.output.suffix == '.gz' else open
        with opener(args.output, 'xt') as output:
            while len(seen) < args.expected_count and time.monotonic() - started < args.max_seconds:
                entry = command(connection, stream, 'BLPOP', key, 1)
                if entry is None:
                    continue
                assert entry[0].decode() == key
                record = json.loads(entry[1])
                identifier = record['bench_id']
                if not identifier.startswith(args.run_id + '-') or identifier in seen:
                    raise RuntimeError('Unexpected or duplicate benchmark ID: ' + identifier)
                seen.add(identifier)
                output.write(json.dumps(record, separators=(',', ':')) + '\n')
                if len(seen) % 1000 == 0:
                    output.flush()
                    print(json.dumps({'collected': len(seen)}), flush=True)
            output.flush()
        remaining = command(connection, stream, 'LLEN', key)
    complete = len(seen) == args.expected_count and remaining == 0
    print(json.dumps({'collected': len(seen), 'expected': args.expected_count,
                      'remaining': remaining, 'complete': complete}), flush=True)
    return 0 if complete else 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--host', required=True)
    parser.add_argument('--port', required=True, type=int)
    parser.add_argument('--expected-count', required=True, type=int)
    parser.add_argument('--max-seconds', required=True, type=int)
    parser.add_argument('--output', required=True, type=Path)
    raise SystemExit(collect(parser.parse_args()))
