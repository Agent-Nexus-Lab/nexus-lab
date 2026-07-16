from __future__ import annotations

import io
import urllib.error
import unittest
from unittest.mock import patch

from experiments.scrapers import cn8n_client


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


class Cn8nClientTest(unittest.TestCase):
    @patch.object(cn8n_client, "_post")
    def test_article_html_returns_plain_text(self, post):
        post.return_value = {
            "code": 0,
            "data": {
                "result": {
                    "title": "活动通知",
                    "html": (
                        "<html><body><script>bad()</script>"
                        "<div id='js_content'><h1>活动通知</h1>"
                        "<p>时间：2026年8月1日</p>"
                        "<p>地点：邯郸校区</p></div></body></html>"
                    ),
                }
            },
        }

        text = cn8n_client.get_article_detail_text("https://mp.weixin.qq.com/s/test")

        self.assertIn("活动通知", text)
        self.assertIn("时间：2026年8月1日", text)
        self.assertNotIn("bad()", text)
        post.assert_called_once_with(
            "/p4/fbmain/monitor/v3/article_html",
            {"url": "https://mp.weixin.qq.com/s/test"},
        )

    @patch.object(cn8n_client, "_post")
    def test_article_html_without_html_is_an_api_error(self, post):
        post.return_value = {"code": 0, "data": {"result": {}}}

        with self.assertRaises(cn8n_client.Cn8nError):
            cn8n_client.get_article_detail_text("https://mp.weixin.qq.com/s/test")

    @patch.object(cn8n_client, "_post")
    def test_article_html_falls_back_when_js_content_is_empty(self, post):
        post.return_value = {
            "code": 0,
            "data": {"result": {"html": "<body><div id='js_content'></div><p>正文</p></body>"}},
        }

        self.assertEqual(
            cn8n_client.get_article_detail_text("https://mp.weixin.qq.com/s/test"),
            "正文",
        )

    @patch.object(cn8n_client, "_api_key", return_value="test-key")
    @patch.object(cn8n_client.time, "sleep")
    @patch.object(cn8n_client.urllib.request, "urlopen")
    def test_transient_http_error_is_retried(self, urlopen, sleep, _api_key):
        error = urllib.error.HTTPError(
            "http://example.test", 502, "Bad Gateway", {}, io.BytesIO(b"")
        )
        urlopen.side_effect = [
            error,
            _Response(b'{"code": 0}'),
            _Response(b'{"code": 0}'),
        ]

        result = cn8n_client._post("/test", {})

        self.assertEqual(result, {"code": 0})
        self.assertGreaterEqual(urlopen.call_count, 2)
        sleep.assert_called_with(1.0)


if __name__ == "__main__":
    unittest.main()
