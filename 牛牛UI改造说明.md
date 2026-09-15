# 牛牛 UI 改造说明

> 本文记录上一轮误做的网页界面。用户已明确要求 PyQt 桌面；当前交付入口见 [PyQt桌面界面说明.md](PyQt桌面界面说明.md)，双击 `启动牛牛平台.command` 启动原生应用。

采用用户提供的 `niuniu_ui_pack` 的深海军蓝、琥珀金、固定侧栏、顶部搜索、研究卡片和牛牛品牌素材，接入现有本地工作台。参考包保持原样，继续使用原生 HTML/CSS/JavaScript 和现有 Python 服务。

## 已接入

- 研究工作台：真实注册因子、模板、实验状态与任务统计，研究架构、Theory Mapping、审计口径、近期实验。
- 统一导航：数据中心、因子库、市场状态、结构与事件、序列规则、理论实验室、实验中心、组合与模拟账户、策略回测、结果对比、系统信息。
- 全局搜索：查询因子、理论模板及实验记录；数据中心提供实验行情快照、股票池与数据范围追溯；回测列表筛选独立成交实验。
- 现有实验表单、报告、观测数据、回放、对比及模拟账户使用统一深色样式。增加窄屏布局、键盘焦点和跳至主内容入口。

参考稿的演示统计没有作为真实结果展示。序列页面浏览现有规则，不含拖拽式编辑器；系统信息为只读；机器学习与实盘未新增。当前数据中心是实验来源追溯，并非全数据源覆盖审计。

## 主要文件

- `src/quantlab/workbench/static/index.html`：页面框架和导航。
- `src/quantlab/workbench/static/style.css`：主题、组件和响应式布局。
- `src/quantlab/workbench/static/workspace.js`：首页、搜索、数据中心、回测列表和系统信息。
- `src/quantlab/workbench/static/app.js`：现有页面路由与分类接线。
- `src/quantlab/workbench/static/assets/`：参考包中的 logo 与横幅。
- `src/quantlab/workbench/server.py`、`pyproject.toml`：静态资源服务和打包声明。

## 启动

```sh
.venv/bin/python -m quantlab.cli serve --output artifacts --data-root /Volumes/Lexar/niuniu-data --port 8766
```

打开 <http://127.0.0.1:8766/>。已有该端口服务时直接访问即可。

## 本轮验证

2026-09-09：`PYTHONPATH=tests .venv/bin/python -m unittest test_workbench test_workbench_jobs -q`，6 项通过。新增 JavaScript 与两张品牌图的实际 HTTP 请求均返回 200，并核对 MIME。

浏览器实际验证：首页真实统计、因子筛选、序列分类、全局搜索、数据快照展开、实验详情、配置校验、回测列表及系统信息；控制台未见错误。表单显示“配置校验通过”，本轮未为 UI 验收提交新实验。检查的旧实验没有 K 线快照，回放页面正确显示缺失说明；本轮没有重新验收完整 K 线播放流程或全部研究计算。

1280、1920 和 390 CSS 像素宽度的首页文档均无横向溢出；桌面及窄屏截图位于 `artifacts/niuniu-ui-acceptance/`。1920 宽度的浏览器截图存在拼接异常，因此交付截图采用默认桌面宽度；宽屏仅确认了 DOM 布局尺寸。验收后已恢复默认浏览器尺寸。

现有实验列表接口在当前产物目录的一次读取约 7.4 秒，首页需等该接口完成；本轮未改变后端索引方式。
