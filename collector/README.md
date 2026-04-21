# 采集中台（Collector）

这是“全国诚信市场建筑管理平台”的数据采集后端。当前版本只采集真实业务数据，聚焦三类：

1. 建筑企业信息（`enterprise`）
2. 从业人员信息（`staff`）
3. 招投标信息（`tender`）

并内置运行稳定性能力：

1. 单实例运行锁（防并发冲突）
2. 重试退避（单源失败不拖垮全局）
3. 失败审计（失败源日志）
4. 增量游标（source-level watermark）

## 目录

```text
collector/
├── cli.py
├── connectors.py
├── models.py
├── normalizer.py
├── pipeline.py
├── quality.py
├── storage.py
├── utils.py
├── config/
│   └── sources.json
└── data/
```

## 如何采集（流程）

每次执行 `run` 都按下面流程走：

1. 读取 `source_registry` 的启用数据源（来自 `config/sources.json`）。
2. 按 `source_type` 调用连接器抓取原始记录写入 `raw_record`。
3. 标准化成统一实体写入 `normalized_entity`。
4. 执行质量校验写入 `quality_issue`。
5. 记录运行摘要到 `ingestion_run`。
6. 更新 `source_cursor`（增量水位）并释放运行锁。

## 如何运行（一步步）

前置环境：

- Python 3.10+（本项目已用 `python3` 验证）

在项目根目录执行：

```bash
cd /mnt/g/mycode/mybuild
```

```bash
python3 -m collector.cli init-db
python3 -m collector.cli run
```

带日志运行：

```bash
python3 -m collector.cli run --log-level INFO
```

如果上次异常中断导致运行锁残留，可以强制解锁后继续：

```bash
python3 -m collector.cli run --force-unlock
```

按“全国全量入口 + 二级入口探测”配置执行：

```bash
python3 -m collector.cli init-db --config collector/config/sources_nationwide_lvl2_full.json
python3 -m collector.cli run --force-unlock
```

说明：

- `init-db` 会把 `config/sources.json` 同步到 `source_registry`。
- 配置里不存在的历史源会自动禁用（避免混跑旧源）。
- 默认数据库路径：`collector/data/collector.db`。

## 如何验证结果

### 1) 直接看 CLI 输出

执行后你会看到类似结果：

```text
[run] sources=4 raw=7 normalized=7 issues=0 failed_sources=0
```

### 2) 用 SQL 验证实体数量

```bash
python3 - << 'PY'
import sqlite3
conn=sqlite3.connect('collector/data/collector.db')
cur=conn.cursor()
run_id=cur.execute('SELECT run_id FROM ingestion_run ORDER BY rowid DESC LIMIT 1').fetchone()[0]
print('latest run_id:', run_id)
for row in cur.execute('SELECT entity_type, COUNT(*) FROM normalized_entity WHERE run_id=? GROUP BY entity_type', (run_id,)):
    print(row)
conn.close()
PY
```

### 3) 导出全国接口候选目录

```bash
python3 -m collector.cli export-interfaces
```

默认输出：

```text
scripts/interface-catalog.json
```

## 数据源配置（`config/sources.json`）

每个数据源字段：

- `source_id`：唯一 ID
- `name`：显示名
- `source_type`：连接器类型（决定抓取逻辑）
- `source_level`：来源分级（A/B/C/D）
- `base_url`：源站基础地址
- `province_code` / `city_code`：行政区划
- `enabled`：是否启用

当前已配置真实源：

- `jzsc_company_live`：四库一平台企业列表真实数据
- `jzsc_staff_live`：四库一平台人员列表真实数据
- `jzsc_project_live`：四库一平台项目列表真实数据（用于招投标/项目主体）

## 省级平台源清单（已建立）

已从国家平台公开跳转入口收集并落地省级源目录（30条）：

- `collector/config/province_sources_seed.json`
  省级平台原始入口清单
- `collector/data/province_reachability.json`
  可达性探测结果（HTTP状态、标题、错误）
- `collector/config/province_sources_catalog.json`
  合并后的优先级目录（`priority=1/2/3`）

优先级规则：

- `priority=1`：可达且标题命中“建筑/市场/监管”等关键词，优先接入采集。
- `priority=2`：可达但关键词弱匹配，次优先接入。
- `priority=3`：当前不可达或超时，进入重试队列。

## 当前真实性说明（重要）

- 现在“企业/人员/项目（招采相关）”三类均为真实网站实时返回数据。
- 四库一平台业务接口为加密响应，系统通过 Playwright 采集浏览器会话响应并在本地解密后入库。
- 不再使用模拟、虚拟、占位数据源。

## 数据库表

- `source_registry`：采集源注册
- `ingestion_run`：采集运行记录
- `raw_record`：原始记录
- `normalized_entity`：标准化主体记录
- `quality_issue`：质量问题
- `source_cursor`：增量游标（每个采集源的水位）
- `source_failure_log`：采集失败审计日志
- `runner_lock`：采集单实例运行锁

## 如何接入真实业务数据（企业/人员/招投标）

1. 在 `connectors.py` 新增 `jzsc_enterprise_live`、`jzsc_staff_live`、`jzsc_tender_live`。
2. 用 Playwright 打开 `https://jzsc.mohurd.gov.cn`，复用浏览器上下文请求业务接口。
3. 把接口响应映射为统一 `RawRecord`，入现有 pipeline（无需改存储层）。
4. 在 `quality.py` 增加业务规则（资质有效期、执业状态、招投标异常金额）。

## 常用命令

```bash
# 初始化源配置与库
python3 -m collector.cli init-db

# 执行采集
python3 -m collector.cli run

# 详细日志
python3 -m collector.cli run --log-level DEBUG

# 异常中断后强制清理运行锁再执行
python3 -m collector.cli run --force-unlock

# 导出接口候选目录
python3 -m collector.cli export-interfaces
```

## 增量采集说明（A1 已接通）

- `source_cursor` 已实际参与 connector 执行，不再只是占位字段。
- `jzsc_staff_by_company_live` / `jzsc_project_by_company_live` 的游标格式为 `enterprise_id:<N>`。
- 运行时只会处理 `normalized_entity.id > N` 的新增企业名，避免每次全量扫描历史企业。
- 若该游标不存在，则默认首跑仍按当前库中企业全量反查一次；跑完后自动写入最新 `enterprise_id`。
