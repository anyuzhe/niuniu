"""手机版部署脚本：nginx 配置内容和参数校验（不连服务器）。"""
import importlib.util
import unittest
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / 'scripts' / 'mobile' / 'deploy_mobile.py'
spec = importlib.util.spec_from_file_location('deploy_mobile', PATH)
dm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dm)


class RenderTests(unittest.TestCase):
    def test_http_only_stage_has_challenge_and_no_ssl(self):
        text = dm.render_nginx('nb-x.example.com', '/www/wwwroot/nb-x.example.com', ssl=False)
        self.assertIn('acme-challenge', text)
        self.assertNotIn('ssl_certificate', text)
        self.assertIn('return 301 https://nb-x.example.com', text)

    def test_full_site_is_https_with_strict_headers(self):
        text = dm.render_nginx('nb-x.example.com', '/www/wwwroot/nb-x.example.com', ssl=True)
        for needle in ('listen 443 ssl http2', '/etc/letsencrypt/live/nb-x.example.com/fullchain.pem', 'Content-Security-Policy',
                       "frame-ancestors 'none'", 'noindex', 'Cache-Control "no-cache"', 'try_files $uri $uri/ =404', 'location ~ /\\.', 'location = /manifest.webmanifest', 'default_type application/manifest+json'):
            self.assertIn(needle, text)
        self.assertNotIn("'unsafe-inline'", text)
        self.assertNotIn('{HEADERS}', text)
        self.assertEqual(text.count('Content-Security-Policy'), 2)        # 两个 location 各带一份（add_header 不继承）
        self.assertNotIn('autoindex', text)
        self.assertEqual(text.count('server_name nb-x.example.com;'), 2)

    def test_rejects_unsafe_values(self):
        for bad in ('x', 'a b.example.com', 'x.example.com;rm', 'EXAMPLE.com', '../x.com', "a'.com"):
            with self.assertRaises(ValueError):
                dm.render_nginx(bad, '/www/wwwroot/x', ssl=True)
        for bad in ('relative', '/a b', '/a/../b', '/a;b'):
            with self.assertRaises(ValueError):
                dm.render_nginx('x.example.com', bad, ssl=True)

    def test_page_sources_exist_and_have_no_inline_style_or_script(self):
        site = dm.SITE_SRC
        for name in ('index.html', 'app.js', 'style.css', 'sw.js', 'manifest.webmanifest', 'icon-180.png', 'icon-192.png', 'icon-512.png'):
            self.assertTrue((site / name).is_file(), name)
        html = (site / 'index.html').read_text(encoding='utf-8')
        self.assertNotIn(' style=', html)            # CSP 不允许内联样式
        self.assertNotIn('<script>', html)
        self.assertNotIn('onclick=', (site / 'app.js').read_text(encoding='utf-8'))
        self.assertNotIn(' style=', (site / 'app.js').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
