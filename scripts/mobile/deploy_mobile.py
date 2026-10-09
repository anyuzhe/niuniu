#!/usr/bin/env python3
"""把手机版网页（web/mobile_bench/）部署到自己的服务器：传文件、建 nginx 站点、用 certbot 申请 HTTPS 证书。

只用标准库，从这台电脑 ssh 过去执行（要求 ssh 能免密登录，BatchMode）。可以反复运行：
  * 页面文件每次都覆盖；data.json（加密快照）不在页面目录里，不会被碰；
  * 站点配置只写 <vhost-dir>/<域名>.conf 这一个文件，不改服务器上任何其它站点；
  * 先用只有 80 端口的配置去申请证书，成功后才写带 HTTPS 的完整配置；写完 nginx -t 不通过就撤回、不重载；
  * 证书用 certbot 的 webroot 方式，服务器上已有的 certbot-renew.timer 会自动续期。

    python scripts/mobile/deploy_mobile.py --host root@47.97.153.8 --domain nb-q7m3.aiiiiai.com
"""
from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SITE_SRC = ROOT / 'web' / 'mobile_bench'
DOMAIN_RE = re.compile(r'^(?=.{4,100}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$')
HOST_RE = re.compile(r'^[A-Za-z0-9_.@-]+$')
PATH_RE = re.compile(r'^/[A-Za-z0-9_./-]+$')

CSP = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


def _headers(indent: str = '        ') -> str:
    lines = ['add_header Cache-Control "no-cache" always;', 'add_header Strict-Transport-Security "max-age=31536000" always;',
             'add_header X-Content-Type-Options nosniff always;', 'add_header Referrer-Policy no-referrer always;',
             'add_header X-Robots-Tag "noindex, nofollow" always;', f'add_header Content-Security-Policy "{CSP}" always;']
    return '\n'.join(indent + x for x in lines)


def render_nginx(domain: str, root: str, *, ssl: bool) -> str:
    """ssl=False：只有 80 端口（申请证书用，同时把其它请求跳到 https）；ssl=True：再加 443 的完整站点。"""
    if not DOMAIN_RE.match(domain):
        raise ValueError('域名不合法')
    if not PATH_RE.match(root) or '..' in root:
        raise ValueError('目录不合法')
    http = f"""server {{
    listen 80;
    server_name {domain};
    root {root};
    location ^~ /.well-known/acme-challenge/ {{ default_type text/plain; try_files $uri =404; }}
    location / {{ return 301 https://{domain}$request_uri; }}
}}
"""
    if not ssl:
        return http
    return http + f"""
server {{
    listen 443 ssl http2;
    server_name {domain};
    root {root};
    index index.html;
    access_log /var/log/{domain}-access.log;
    error_log /var/log/{domain}-error.log warn;

    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:NIUNIU_BENCH_SSL:5m;
    ssl_session_timeout 10m;

    gzip on;
    gzip_types application/json application/javascript text/css application/manifest+json;
    gzip_min_length 1024;

    # 页面和数据每次都问服务器有没有新的（文件很小），推了新快照手机下次打开就是新的
    location / {{
{{HEADERS}}
        try_files $uri $uri/ =404;
    }}
    location = /manifest.webmanifest {{
        default_type application/manifest+json;
{{HEADERS}}
    }}
    location ~ /\\. {{ deny all; }}
}}
""".replace('{HEADERS}', _headers())


def sh(host: str, command: str, *, data: bytes | None = None, check: bool = True, timeout: float = 300) -> subprocess.CompletedProcess:
    proc = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', host, command], input=data,
                          capture_output=True, timeout=timeout)
    if check and proc.returncode != 0:
        raise RuntimeError(f'远程命令失败（{proc.returncode}）：{command[:80]}\n{proc.stderr.decode("utf-8", "replace").strip()[-600:]}')
    return proc


def upload_site(host: str, root: str) -> int:
    files = sorted(p for p in SITE_SRC.iterdir() if p.is_file() and not p.name.startswith('.'))      # 不带 macOS 的 ._ 副产品
    if not files:
        raise RuntimeError(f'{SITE_SRC} 里没有页面文件')
    tar = subprocess.run(['tar', '-C', str(SITE_SRC), '-cf', '-'] + [p.name for p in files], capture_output=True, check=True,
                         env={'COPYFILE_DISABLE': '1', 'PATH': '/usr/bin:/bin'})
    sh(host, f'mkdir -p {shlex.quote(root)} && tar -C {shlex.quote(root)} -xf - && chmod 755 {shlex.quote(root)} && chmod 644 {shlex.quote(root)}/*', data=tar.stdout)
    return len(files)


def write_conf(host: str, conf_path: str, text: str) -> None:
    sh(host, f'cat > {shlex.quote(conf_path)}.new && mv {shlex.quote(conf_path)}.new {shlex.quote(conf_path)}', data=text.encode('utf-8'))


def reload_nginx(host: str) -> None:
    sh(host, 'nginx -t && nginx -s reload')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='部署手机版网页到自己的服务器')
    ap.add_argument('--host', required=True, help='ssh 地址，如 root@1.2.3.4')
    ap.add_argument('--domain', required=True, help='站点域名（二级域名要已解析到服务器）')
    ap.add_argument('--webroot', default='/www/wwwroot', help='服务器上放站点的目录')
    ap.add_argument('--vhost-dir', default='/www/server/panel/vhost/nginx', help='nginx 站点配置目录（宝塔默认）')
    ap.add_argument('--print-conf', action='store_true', help='只打印 nginx 配置，不连服务器')
    args = ap.parse_args(argv)
    if not HOST_RE.match(args.host) or not DOMAIN_RE.match(args.domain) or not PATH_RE.match(args.webroot) or not PATH_RE.match(args.vhost_dir):
        ap.error('参数含有不允许的字符')
    root = f'{args.webroot.rstrip("/")}/{args.domain}'
    conf = f'{args.vhost_dir.rstrip("/")}/{args.domain}.conf'
    if args.print_conf:
        print(render_nginx(args.domain, root, ssl=True))
        return 0

    print('1/5 上传页面文件 …', upload_site(args.host, root), '个')
    have_cert = sh(args.host, f'test -s /etc/letsencrypt/live/{args.domain}/fullchain.pem', check=False).returncode == 0
    old = sh(args.host, f'cat {shlex.quote(conf)} 2>/dev/null', check=False).stdout
    try:
        if not have_cert:
            print('2/5 写 80 端口配置并重载 …')
            write_conf(args.host, conf, render_nginx(args.domain, root, ssl=False))
            reload_nginx(args.host)
            print('3/5 申请 HTTPS 证书（Let\'s Encrypt）…')
            sh(args.host, f'certbot certonly --webroot -w {shlex.quote(root)} -d {args.domain} --non-interactive --agree-tos --keep-until-expiring')
        else:
            print('2/5、3/5 证书已有，跳过')
        print('4/5 写完整站点配置并重载 …')
        write_conf(args.host, conf, render_nginx(args.domain, root, ssl=True))
        reload_nginx(args.host)
    except Exception:
        # 撤回：恢复原来的配置（没有就删掉我们写的），再检查一次 nginx，保证其它站点不受影响
        if old:
            write_conf(args.host, conf, old.decode('utf-8'))
        else:
            sh(args.host, f'rm -f {shlex.quote(conf)} {shlex.quote(conf)}.new', check=False)
        sh(args.host, 'nginx -t && nginx -s reload', check=False)
        raise
    print('5/5 验证 …')
    out = subprocess.run(['curl', '-sS', '-o', '/dev/null', '-w', '%{http_code}', '--max-time', '20', f'https://{args.domain}/'], capture_output=True, text=True)
    print('https 状态码：', out.stdout.strip() or out.stderr.strip())
    return 0 if out.stdout.strip() == '200' else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print('失败：', exc, file=sys.stderr)
        raise SystemExit(2)
