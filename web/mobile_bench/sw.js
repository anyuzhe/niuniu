/* 牛牛策略（手机只读版）：离线外壳。页面文件先缓存，断网时显示上次快照。
   data.json 网络优先，失败时回退缓存；命中缓存时响应头带 x-sw-cache: true，页面据此显示离线提示。 */
const CACHE = 'niuniu-bench-v19';
const SHELL = ['./', 'index.html', 'style.css', 'app.js', 'manifest.webmanifest', 'icon-192.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

function pathnameOf(url) {
  const p = new URL(url).pathname;
  return p.endsWith('/') ? './' : (p.split('/').pop() || './');
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  const pathname = pathnameOf(req.url);

  if (pathname === 'data.json') {
    // 加密快照：网络优先，失败回退缓存；命中缓存时标记头部，页面据此提示离线
    e.respondWith(
      fetch(req, { cache: 'no-store' })
        .then((res) => {
          if (res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(pathname, copy));
          }
          return res;
        })
        .catch(() => caches.match(pathname).then((hit) => {
          if (hit) {
            const hdrs = new Headers(hit.headers);
            hdrs.set('x-sw-cache', 'true');
            return new Response(hit.body, { status: hit.status, statusText: hit.statusText, headers: hdrs });
          }
          return Response.error();
        }))
    );
    return;
  }

  e.respondWith(
    fetch(req, { cache: 'no-store' })
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(pathname, copy));
        }
        return res;
      })
      .catch(() => caches.match(pathname).then((hit) => hit || Response.error()))
  );
});
