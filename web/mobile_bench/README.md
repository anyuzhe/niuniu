# 牛牛策略（手机版）

策略工作台的只读手机网页（PWA）。电脑上的牛牛把信号、前向台账、持仓清单加密成一份 `data.json`
推到自己的服务器，这里的页面下载后在手机本地解密显示。**没有后端程序**，服务器上只有静态文件。

```
电脑（牛牛）──加密 data.json──▶ 服务器 nginx（静态）◀──HTTPS── 手机（输入口令，本地解密）
```

## 第一次设置（电脑上做一次）

```bash
# 1) 部署页面：传文件、建 nginx 站点、申请 HTTPS 证书（要求 ssh 能免密登录，二级域名已解析到服务器）
python scripts/mobile/deploy_mobile.py --host root@服务器IP --domain 二级域名

# 2) 告诉牛牛往哪推，并生成口令（口令存在 artifacts/_home/mobile_passphrase，权限 600）
python -m quantlab.dipbuy.mobile_export setup --output artifacts \
    --host root@服务器IP --remote-dir /www/wwwroot/二级域名 --url https://二级域名

# 3) 先推一次
python -m quantlab.dipbuy.mobile_export push --output artifacts

# 4) 手机 Safari 打开网址 → 输入口令 → 分享 → 添加到主屏幕
cat artifacts/_home/mobile_passphrase
```

之后不用管：牛牛开着时，每次数据变新、台账记完会自动推；电脑上改了持仓也会立刻重推。
想手动更新：重复第 3 步。换口令：`setup ... --new-passphrase`，再 `push`，手机要重新输入。

## 安全

- 服务器和网络上只有密文（AES-256-GCM，口令经 PBKDF2-SHA256 30 万次迭代派生密钥）；口令只在电脑和手机上。
- 手机页只读，没有任何写入接口；页面不向任何地址发送数据（CSP `connect-src 'self'`）。
- 口令保存在手机浏览器的本地存储里，“说明”页底部可以忘记口令并锁定。

## 文件

| 文件 | 作用 |
|---|---|
| `index.html` `style.css` `app.js` | 页面（无框架、无外部依赖） |
| `sw.js` | 离线外壳：断网时显示上次的快照 |
| `manifest.webmanifest` `icon-*.png` | 添加到主屏幕用 |
| `../../src/quantlab/dipbuy/mobile_export.py` | 快照 / 加密 / 推送（电脑端） |
| `../../scripts/mobile/deploy_mobile.py` | 部署脚本 |
