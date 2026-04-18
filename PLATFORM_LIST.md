# 全国建筑市场监管平台完整目录

> 整理时间：2026-04-18
> 检测方式：Playwright (headless Chromium, ignore_https_errors)
> 说明：⚠️ 标记的条目可能因当前出口 IP 位于境外/非中国IP，被部分政府平台拒绝连接，需在中国大陆网络环境下复验。

---

## 一、国家级平台（1个）

| 平台名称 | 网址 | 状态 | 说明 |
|---------|------|------|------|
| 全国建筑市场监管公共服务平台（四库一平台） | https://jzsc.mohurd.gov.cn | ✅ 正常 | 住建部主办，含企业/人员/项目/诚信数据，API 需 AES-CBC 解密 |

---

## 二、省级平台（31个 + 1个直辖市）

| # | 省份 | 平台名称 | 验证URL | 状态 | 备注 |
|---|------|---------|---------|------|------|
| 1 | 北京 | 北京市住房和城乡建设委员会 | http://zjw.beijing.gov.cn/ | ✅ 正常 | 建筑市场数据入口 |
| 2 | 天津 | 天津市住房和城乡建设委员会 | https://szzj.zfcxjs.tj.gov.cn:30479/ | ✅ 正常 | 独立监管平台 |
| 3 | 河北 | 河北省建筑市场监管公共服务平台 | http://121.29.49.134:18000/ | ✅ 正常 | |
| 4 | 山西 | 山西省智慧建筑管理服务信息平台 | http://183.201.195.143:28800/webserver/publish/index.html | ✅ 正常 | |
| 5 | 内蒙古 | 内蒙古自治区建筑工程监管公共服务信息平台 | http://110.16.70.26:82/nmjgpublish/index.html | ✅ 正常 | |
| 6 | 辽宁 | 辽宁监管平台 | http://218.60.154.1:81/webserver/lnpublish/index.html | ✅ 正常 | |
| 7 | 吉林 | 吉林省建筑市场监管公共服务平台 | https://cx.jlsjsxxw.com:8084/ | ✅ 正常 | |
| 8 | 黑龙江 | 黑龙江省建筑市场监管平台 | http://112.103.231.221:8095/cmspsp/indexAction_queryHomeData.action | ⚠️ 超时 | **当前不可达**，可能已迁移或 IP 限制，需国内网络复验 |
| 9 | 上海 | 上海市住房和城乡建设管理委员会 | https://zjw.sh.gov.cn/ | ✅ 正常 | |
| 10 | 江苏 | 江苏省建筑市场监管平台 | http://58.213.147.230:7001/Jsjzyxyglpt/faces/public/default.jsp | ⚠️ 超时 | **当前不可达**，可能已迁移，需国内网络复验 |
| 11 | 浙江 | 浙江省建筑市场监管公共服务系统 | https://jzsc.jst.zj.gov.cn/PublicWeb/index.html | ✅ 正常 | |
| 12 | 安徽 | 安徽省住房和城乡建设厅业务系统 | https://dohurd.ah.gov.cn/zwfw/xtbgpt/index.html | ✅ 正常 | |
| 13 | 福建 | 福建省建设工程监管一体化平台 | https://220.160.52.164:20082/login | ✅ 正常 | |
| 14 | 江西 | 江西住建云 | https://zjy.jxjst.gov.cn/ | ✅ 正常 | |
| 15 | 山东 | 山东省建筑市场监管与诚信信息一体化平台 | http://221.214.94.41:81/xyzj/DTFront/ZongHeSearch/?searchType=1 | ✅ 正常 | |
| 16 | 河南 | 河南省建筑市场监管公共服务平台 | http://hngcjs.hnjs.henan.gov.cn/ | ✅ 正常 | |
| 17 | 湖北 | 湖北省建筑市场监管平台 | http://jg.hbcic.net.cn/web/ | ⚠️ 503 | **503 Service Unavailable**，服务器端临时不可用或已下线 |
| 18 | 湖南 | 湖南省建筑市场监管公共服务平台 | https://gcxm.hunanjs.gov.cn/ | ✅ 正常 | |
| 19 | 广东 | 广东省建筑市场监管公共服务平台 | https://scjg.gdcic.net/ | ✅ 正常 | |
| 20 | 广西 | 广西建筑市场监管云平台（桂建云） | https://gxjzsc.gxcic.net/ | ✅ 正常 | HTTP 可达，HTTPS 证书问题 |
| 21 | 海南 | 海南省住房和城乡建设厅 | https://zjt.hainan.gov.cn/ | ✅ 正常 | **新发现 URL**，原 URL `www.hizj.net:8008` 已废弃 |
| 22 | 重庆 | 重庆市建筑市场监管平台 | http://www.cqjsxx.com/webcqjg/Index.aspx | ⚠️ 400 | HTTP→HTTPS 端口问题，需确认正确协议 |
| 23 | 四川 | 四川省建筑市场监管公共服务平台 | http://202.61.88.188/xmgk/yth/index.aspx | ✅ 正常 | |
| 24 | 贵州 | 贵州省建筑市场监管平台 | http://61.243.11.50:8088/GZZHXT/Index.html | ⚠️ 超时 | **当前不可达**，IP 可能在境外被屏蔽，需国内网络复验 |
| 25 | 云南 | 云南省建筑市场监管平台 | http://www.ynjzjgcx.com/ | ⚠️ 400 | HTTP→HTTPS 端口问题，原 URL 可能已强制 HTTPS |
| 26 | 西藏 | 西藏自治区住房和城乡建设厅 | http://zjt.xizang.gov.cn/ | ✅ 正常 | |
| 27 | 陕西 | 陕西省住房和城乡建设厅 | http://js.shaanxi.gov.cn/ | ✅ 正常 | **新发现 URL**，`jzsc.shaanxi.gov.cn` 域名当前不可达 |
| 28 | 甘肃 | 甘肃省建筑市场监管平台 | http://zjt.gansu.gov.cn/ | ⚠️ 412 | HTTP→HTTPS 协议问题，原 URL 强制 HTTPS 但返回 412 |
| 29 | 青海 | 青海省工程建设监管和信用管理平台 | http://139.170.150.135/asite/cloud/index | ✅ 正常 | |
| 30 | 宁夏 | 宁夏建筑市场监管平台 | http://www.nxjscx.com.cn/index.htm | ⚠️ 超时 | **当前不可达**，nxjzsc.nxjscx.com（Cloudflare 保护）需进一步探测 |
| 31 | 新疆 | 新疆工程建设云 | https://jsy.xjjs.gov.cn/ | ✅ 正常 | |

---

## 三、平台可用性汇总

| 状态 | 数量 | 省份 |
|------|------|------|
| ✅ 直通（可正常访问） | **22** | 北京、天津、河北、山西、内蒙古、辽宁、吉林、上海、浙江、安徽、福建、江西、山东、河南、湖南、广东、广西、海南（厅首页）、四川、西藏、陕西（厅首页）、青海、新疆 |
| ⚠️ 需国内网络复验 | **7** | 黑龙江、江苏、湖北、重庆（端口问题）、贵州、云南（端口问题）、宁夏 |
| ⚠️ 协议/端口问题 | **2** | 重庆（HTTP vs HTTPS）、甘肃（HTTP vs HTTPS） |

**总计：31 个省级平台，22 个当前可直接访问，9 个需在中国大陆 IP 环境下复验或修复 URL/协议。**

---

## 四、待修复/确认事项

### 4.1 必须修复 URL（协议/端口问题）

| 省份 | 当前错误 | 建议操作 |
|------|---------|---------|
| 重庆 | HTTP 400 (发给 HTTPS 端口) | 改为 `https://www.cqjsxx.com/webcqjg/Index.aspx` 或 `https://jzsc.cq.gov.cn/` |
| 甘肃 | HTTPS 412 | 改为 `https://zjt.gansu.gov.cn/`（强制 HTTPS 访问） |
| 云南 | HTTP 400 | 改为 `https://www.ynjzjgcx.com/` 或 `http://www.ynjzjg.com/` |

### 4.2 需国内网络复验（IP 限制，当前不可达）

| 省份 | 原 URL | 可能的替代 URL |
|------|--------|--------------|
| 黑龙江 | `112.103.231.221:8095` | `http://hljjs.hljjs.gov.cn/` 或搜索"黑龙江省建筑市场监管公共服务平台" |
| 江苏 | `58.213.147.230:7001` | `https://jzsc.jiangsu.gov.cn/` 或 `http://www.jsbuild.gov.cn/` |
| 湖北 | `jg.hbcic.net.cn` (503) | `http://jzsc.hbjs.gov.cn/` 或联系平台确认新域名 |
| 贵州 | `61.243.11.50:8088` | `http://gzjzsc.guizhou.gov.cn/` 或 `http://61.243.11.51:8080/` |
| 宁夏 | `nxjscx.com.cn` | `https://zfcx.nx.gov.cn/` (宁夏政务网) 或 `https://nxjzsc.nxjscx.com/` (Cloudflare 拦截) |

### 4.3 新发现的可用平台（未在现有配置中）

| 省份 | 新发现 URL | 来源 |
|------|-----------|------|
| 海南 | `https://zjt.hainan.gov.cn/` | 备用探测，厅首页含建设入口 |
| 陕西 | `http://js.shaanxi.gov.cn/` | 备用探测，住建厅首页 |
| 广西 | `http://gxjzsc.gxcic.net/` | HTTP 版本，绕过 SSL 问题 |

---

## 五、数据采集建议

| 省份类型 | 采集策略 |
|---------|---------|
| 22 个已通省份 | 直接接入 HTTP/HTTPS，逐步建立业务数据连接器 |
| 9 个待复验省份 | 先标记为 `enabled=false`，待国内网络复验后启用 |
| 北京 | 仅有住建委首页，需从国家平台四库一平台获取北京企业数据（北京企业通常也上报国家平台） |

---

## 六、配置更新建议

将以下新发现的可用 URL 更新到 `collector/config/sources.json` 和 `province_sources_catalog.json`：

```json
[
  { "province": "海南", "prov_20", "url": "https://zjt.hainan.gov.cn/", "title": "海南省住房和城乡建设厅" },
  { "province": "陕西", "prov_26", "url": "http://js.shaanxi.gov.cn/", "title": "陕西省住房和城乡建设厅" },
  { "province": "广西", "prov_19", "url": "http://gxjzsc.gxcic.net/", "title": "广西建筑市场监管云平台" }
]
```

将以下协议错误 URL 修复：

```json
[
  { "province": "重庆", "url": "https://jzsc.cq.gov.cn/" },
  { "province": "甘肃", "url": "https://zjt.gansu.gov.cn/" },
  { "province": "云南", "url": "https://www.ynjzjgcx.com/" }
]
```