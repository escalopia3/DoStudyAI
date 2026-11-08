"""Explicit host allowlist, public IP pinning, HTTPS only, no redirects/proxies."""
import http.client
import ipaddress
import os
import socket
import ssl
from urllib.parse import urlsplit
from dovideo.validation import InvalidResource

def validate_url(url):
    parts = urlsplit(url)
    allowed = {x.strip().lower() for x in os.getenv('DOVIDEO_IMPORT_HOSTS', '').split(',') if x.strip()}
    if (parts.scheme != 'https' or not parts.hostname or parts.hostname.lower() not in allowed
        or parts.username or parts.password or parts.port not in (None,443) or parts.fragment):
        raise InvalidResource('URL_NOT_ALLOWED')
    return parts

def open_source(url):
    parts = validate_url(url)
    addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise InvalidResource('NON_PUBLIC_ADDRESS')
    connection = http.client.HTTPSConnection(parts.hostname, timeout=15, context=ssl.create_default_context())
    raw = socket.create_connection((addresses[0][4][0],443), timeout=15)
    try:
        connection.sock = connection._context.wrap_socket(raw, server_hostname=parts.hostname)
        path = (parts.path or '/') + ('?' + parts.query if parts.query else '')
        connection.request('GET', path,
                           headers={'Accept-Encoding':'identity','User-Agent':'DoVideo-Importer/1'})
        response = connection.getresponse()
        if response.status != 200:
            raise InvalidResource('SOURCE_HTTP_STATUS')
        return connection, response
    except Exception:
        raw.close()
        connection.close()
        raise
