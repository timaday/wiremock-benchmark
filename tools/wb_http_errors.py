"""Responsibility: classify HTTP transport failures for safe CLI diagnostics.

Must not: expose raw exception messages, retry requests or change configuration.
Contract: docs/WB.md, connection failure diagnostics.
"""

import errno
import socket
import ssl
from urllib.error import URLError


def transport_failure(error):
    reason = error.reason if isinstance(error, URLError) else error
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "TLS certificate verification failed"
    if isinstance(reason, ssl.SSLError):
        return "TLS connection failed"
    if isinstance(reason, socket.gaierror):
        return "DNS resolution failed"
    if isinstance(reason, TimeoutError):
        return "connection/read timed out"
    if isinstance(reason, OSError):
        descriptions = {
            errno.ECONNREFUSED: "connection refused",
            errno.ECONNRESET: "connection reset by peer",
            errno.ENETUNREACH: "network unreachable",
            errno.EHOSTUNREACH: "host unreachable",
            errno.EACCES: "connection denied by local permissions",
            errno.EPIPE: "connection closed (broken pipe)",
        }
        if reason.errno in descriptions:
            return descriptions[reason.errno]
    # Unknown failures retain their exception category, never arbitrary text.
    return type(reason).__name__ if isinstance(reason, BaseException) else "unclassified transport error"
