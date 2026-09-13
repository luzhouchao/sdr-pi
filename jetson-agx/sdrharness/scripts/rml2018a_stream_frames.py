"""Bounded Controller stream pipe framing; binary IQ is never parsed as JSON."""
import json
import rml2018a_campaign as c


def read_frame(stream):
    line = stream.readline(2049)
    if not line: raise EOFError('Controller stream ended without rx_end')
    c.require(len(line) <= 2048 and line.endswith(b'\n'), 'stream header bound')
    header = json.loads(line)
    c.require(header.get('schema_version') == 1 and header.get('event') in ('rx_ready','rx_chunk','rx_end'), 'stream event schema')
    count = header.get('bytes', 0)
    if header['event'] == 'rx_chunk':
        c.require(type(count) is int and 0 < count <= 256*1024 and count%4 == 0, 'stream payload bound')
    else: c.require(count == 0, 'control event has no payload')
    chunks = []; remaining = count
    while remaining:
        part = stream.read(remaining)
        if not part: raise EOFError('truncated Controller IQ payload')
        chunks.append(part); remaining -= len(part)
    return header, b''.join(chunks)
