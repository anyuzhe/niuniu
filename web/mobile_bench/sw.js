/* 离线外壳：页面文件和数据都是“先联网、失败再用上次的”，所以改了页面或推了新数据，下次打开就是新的。
   缓存里存的 data.json 仍是密文，和服务器上的一样。 */
const CACHE = 'niuniu-bench-v1';
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

self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  e.respondWith(
    fetch(req, { cache: 'no-store' })
      .then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(url.pathname.endsWith('/') ? './' : url.pathname.split('/').pop() || './', copy));
        }
        return res;
      })
      .catch(() => caches.match(url.pathname.endsWith('/') ? './' : url.pathname.split('/').pop() || './').then((hit) => hit || Response.error()))
  );
});
