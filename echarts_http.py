# -*- coding: utf-8 -*-
"""
echarts_http.py — 本地 HTTP 服务（独立模块）
─────────────────────────────────────────────
负责：为本地 ECharts 静态资源提供 HTTP 服务，供 QWebEngineView 加载。
从 bitable.py 的 HTTP 服务器功能独立出来，bitable 删除后 dashboard 仍能正常使用。
"""

import os
import logging
import socketserver
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

logger = logging.getLogger(__name__)


class _QuietEchartsHandler(SimpleHTTPRequestHandler):
    """静默 HTTP 请求处理器，服务项目根目录（供 echarts/ 目录访问）"""
    _echarts_dir = None

    def log_message(self, format, *args):
        pass

    def translate_path(self, path):
        """将 /echarts/* URL 映射到 echarts 目录"""
        from urllib.parse import unquote
        path = unquote(path.split('?', 1)[0].split('#', 1)[0])
        rel = path.lstrip('/')
        if rel.startswith('echarts/') and self._echarts_dir:
            return os.path.join(self._echarts_dir, rel[len('echarts/'):])
        return os.path.join(self.directory, rel)


ECHARTS_PORT = None


def start_echarts_http(project_dir: str = '') -> int:
    """启动本地 HTTP 服务器，服务项目根目录（供 echarts/ 目录访问）。
    端口范围 19000-19099。"""
    global ECHARTS_PORT
    if ECHARTS_PORT is not None:
        return ECHARTS_PORT

    if not project_dir:
        project_dir = os.path.dirname(os.path.abspath(__file__))

    _QuietEchartsHandler._echarts_dir = project_dir

    handler = partial(_QuietEchartsHandler, directory=project_dir)

    class _TCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    for port in range(19000, 19100):
        try:
            httpd = _TCPServer(("127.0.0.1", port), handler)
            ECHARTS_PORT = port
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            logger.info(f"[Echarts] HTTP server started: http://127.0.0.1:{port}")
            return port
        except OSError:
            continue

    logger.error("[Echarts] No available port found (19000-19099)")
    return 19000
