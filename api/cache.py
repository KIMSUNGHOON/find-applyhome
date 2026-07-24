"""Vercel 캐시 조회 진입점. 로직은 _lib 에 있다."""

import pathlib
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import _lib


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _lib.respond(self, *_lib.cache_snapshot(query))
