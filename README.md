# 全国诚信市场建筑管理平台

当前仓库包含两部分：

1. 静态前端门户（展示页面）
2. 采集中台骨架（数据源注册、采集、标准化、质检、入库）

## 目录结构

```text
.
├── index.html
├── pages/
├── scripts/
├── styles/
└── collector/
```

## 本地查看

直接在浏览器打开 `index.html` 即可，或使用任意静态服务器运行。

例如：

```bash
python3 -m http.server 8080
```

然后访问：

```text
http://localhost:8080
```

## 采集中台快速开始

先进入项目根目录：

```bash
cd /mnt/g/mycode/mybuild
```

初始化并运行采集：

```bash
python3 -m collector.cli init-db
python3 -m collector.cli run
```

SQLite 数据库默认路径：

```text
collector/data/collector.db
```

采集细节与验证命令见 [collector/README.md](/mnt/g/mycode/mybuild/collector/README.md)。

当前采集实体类型：

1. `enterprise`（建筑企业）
2. `staff`（从业人员）
3. `tender`（招投标）

全国全量平台入口与二级探测可执行：

```bash
python3 -m collector.cli init-db --config collector/config/sources_nationwide_lvl2_full.json
python3 -m collector.cli run --force-unlock
python3 -m collector.cli export-interfaces
```

接口候选目录输出到：

```text
scripts/interface-catalog.json
```

## 下一步可扩展

1. 接入真实省市数据源连接器（API + 公告页 + 文件导入）。
2. 增加增量同步机制与任务调度（cron/Airflow）。
3. 增加对外查询 API 和后台管理页面。
4. 建立城市级统计与预警模型。
