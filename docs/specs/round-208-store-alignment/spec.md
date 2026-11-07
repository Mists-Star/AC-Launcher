# round-208 — 资源中心「99% 代码级对齐」对照规格

> **决策来源**：主理人「这样，我们直接仿照其他启动器学一遍吧」→ 选择「整套对齐含整页重做」→ 追加
> 「注意是 99% 的代码参考学习」。
> **本文件性质**：Task #353 的交付物。逐条写清「上游怎么做（含 `repo:path:line` 与代码片段）→
> AC 落到哪个文件/函数 → 用哪条回归断言证明落地」。**规格拍板前不动 UI 源码**。
> **日期**：2026-11-07 ｜ 关联：`docs/quality_punchlist.md` §十四、`CHANGELOG.md` round-207。

---

## 0. 调研方法与证据链

### 0.1 上游源码（全部实读，非截图/印象）

| 代号 | 仓库 | 分支 | tree SHA（抓取时） | 文件树 | 许可 |
|---|---|---|---|---|---|
| `prism` | `PrismLauncher/PrismLauncher` | `develop` | `899d2f3957215a09fe398a8a8cbb8a8a9c619968` | 1758 文件 / 未截断 | GPL-3.0 |
| `hmcl` | `HMCL-dev/HMCL` | `main` | `3e172608bfbad847a8962218edcc62dff0003749` | 1378 文件 / 未截断 | GPL-3.0 |
| `pclce` | `PCL-Community/PCL-CE`（PCL2 社区版） | `dev` | `2585c149e3b87380735ab9b5fa7e20fac2c9fb41` | 1399 文件 / 未截断 | 主体自定义许可 + 外围 Apache-2.0 |

- 官方 PCL2 `Hex-Dragon/PCL2` 已 **301 迁到 `Meloong-Git/PCL`**（`main`）；社区版 `PCL2-CE/PCL2-CE`
  实为 `PCL-Community/PCL-CE`（`dev`）。这两处仓库名此前记错过，本轮已用 API 核实。
- `Meloong-Git/PCL` 的完整文件树因共享代理 IP 触发 GitHub API 限流（HTTP 403）未取到；
  `PCL-CE` 是「基于 PCL2 开源代码二次开发」的同源分支，本轮以它作为 **PCL2 系的代码级代表**。
  结论中凡涉及 PCL2 系，一律标 `pclce:`，不假装读过官方树。

### 0.2 抓取方式

- 直连 `api.github.com` 在本环境超时（沙箱代理劫持，见项目既有结论）；有效通道是
  `https://gh-proxy.com/` 与 `https://v6.gh-proxy.org/` 前缀转发。
- API 通道用于 **文件树定位**（`/repos/<repo>/git/trees/<branch>?recursive=1`）；
  **源码正文一律走 `raw.githubusercontent.com` 转发**，绕开 API 限流。
- 共落地 **57 个上游源码文件**快照，路径保持仓库原始结构，存于 `_scratch/upstream/src/<代号>/…`
  （`.gitignore` 已加 `_scratch/`，快照不入库，需要时按 §0.1 的 tree SHA 可原样复取）。
- 抓取脚本：`_scratch/upstream/fetch_tree.py` / `fetch_files.py` / `fetch_pcl.py` / `fetch_extra.py`。

### 0.3 「99%」的定义与那 1%

- **99% = 上游 12 项可观测行为逐条对齐**（§2），每项都有上游行号、AC 落地点、回归断言；
  不新造 IA、不凭印象补功能、不把「差不多」当对齐。
- **1% 的偏离只有四类，且必须显式登记**：
  1. AC 品牌视觉（配色 / 圆角 / 图标体系 / `ui_kit` 组件）不照搬上游皮肤；
  2. 中文文案走 `src/i18n.py` 中英对称门禁，不复制上游翻译字符串；
  3. 无官方 CF key 时继续走 `mod.mcimirror.top` 公益镜像（round-140 主理人拍板），
     不为了「像别人」悄悄换后端；
  4. 沿用 AC 既有的 `Worker` / `TrackedThread` / `ImageLoader` 基础设施，不移植 Qt/C++/Java 线程模型。

### 0.4 合规边界

上游 Prism / HMCL 为 GPL-3.0，PCL2 主体为自定义许可。本规格只复刻 **可观测行为、URL 参数、
状态机与信息架构**；**不复制任何上游源码文本进本仓库**，文档中的片段仅为调研引用。
AC 计划以 GPL-3.0 开源，仍不做整段搬运。既有红线不变：不逆向、不复制专有资源。

---

## 1. 三家 IA 对照（先看差异，再定蓝本）

| 维度 | Prism（三栏） | PCL-CE（顶部筛选 + 网格） | HMCL（数据层） | AC 现状 |
|---|---|---|---|---|
| 页面骨架 | `QSplitter` 三格：筛选 / 列表 / 详情 | 筛选卡 + 虚拟化卡片网格 + 页码器 | 仓库层无 UI 约束 | 顶部横排 + 卡片流 + 详情整页栈切换 |
| 筛选 | 侧栏：加载器 / 版本 / 环境 / 已装 / 开源 / 发布渠道 | 顶部：来源 / 分类 / 排序 / 版本 / 加载器 | 服务端过滤参数齐备 | 仅有来源下拉、目标实例、分类胶囊 |
| 排序 | `sortByBox` → 服务端 `sortField` / `index` | `ComboSearchSort` 六档 → 服务端参数 | `SortType` + `SortOrder` | 写死 CF `sortField=1`、MR 默认 |
| 分页 | 无限滚动 `fetchMore`，`limit=25` | **真页码器**，`PageSize=40` | `pageOffset * pageSize` + 总页数 | 无限滚动 `_more()` + `_has_more` |
| 双源 | 每源一个 Page（Modrinth / Flame 分页签） | 单页双源合并，各自 offset/total 游标 | 每源一个 Repository | 单页双源合并 + 按源渐进渲染 |
| 图标 | 占位图立即返回 + `QPixmapCache` + 落盘 | 卡片 VM 字段化 | — | 异步 6 并发 + 磁盘缓存 + 负缓存 |
| 缓存 | `metacache` 落盘 + 内存 pixmap | ETag / Last-Modified + 304 + TTL | 下载源候选回退 | 内存 30min / 磁盘 24h，过期即等网络 |

**结论**：三家在「服务端过滤 + 立即渲染 + 缓存」上完全一致，分歧只在 **版式与分页**。
本规格采用 **Prism 的骨架与状态机 + PCL-CE 的筛选项与双源游标 + HMCL/Prism 的 URL 参数**，
即 §2 的 12 条。版式分歧见 §4，需主理人拍板。

---

## 2. 逐条对照规格

### 2.1 三栏骨架（筛选 / 结果 / 详情同屏）

**上游证据** `prism:launcher/ui/pages/modplatform/ResourcePage.ui:29-62`

```xml
<widget class="QSplitter" name="splitter">
 <property name="childrenCollapsible"><bool>false</bool></property>
 <widget class="QWidget" name="filterWidget" native="true"/>
 <widget class="QListView" name="packView">…</widget>
 <widget class="ProjectDescriptionPage" name="packDescription">…</widget>
</widget>
```

顶部 `:15-26` 是「Filter options 按钮 + 搜索框」，底部 `:65-85` 是「排序 / 已选版本 / 选择按钮」。
筛选面板可折叠：`prism:launcher/ui/pages/modplatform/ModPage.cpp:125-128` 用
`m_filterWidget->setHidden(!m_filterWidget->isHidden())`；面板注入用
`prism:…/ModPage.cpp:103-121` 的 `splitter->replaceWidget(0, widget)`，并把
`filterChanged` 直接接到 `triggerSearch`。

- **AC 落地点**：`src/pages_browse.py:433-529` 的 `StorePage` 根布局 → 换成 `QSplitter`；
  `self._stack`（`:527-529`）不再承载「列表 ↔ 详情」整页切换，详情改为第三格。
- **断言点**：`StorePage` 存在 `QSplitter`，且 `count() == 3`；`_open_detail()` 不切换
  `QStackedWidget` 的当前页，而是写入第三格。

### 2.2 筛选侧栏字段（不新造筛选项）

**上游证据** `prism:launcher/ui/widgets/ModFilterWidget.ui`

| 字段 | 行号 | 控件 |
|---|---|---|
| 加载器（NeoForge/Forge/Fabric/Quilt + Show More） | `:85-125`、`:150-186` | `QCheckBox` |
| MC 版本（含 Show all versions） | `:198-224` | `QComboBox` + `QCheckBox` |
| 运行环境（client/server） | `:226-253` | `QCheckBox` |
| 隐藏已安装 / 仅开源 | `:255-267` | `QCheckBox` |
| 发布渠道（release/beta/alpha/unknown） | `:269-296` | `QCheckBox` |
| 分类 | `:72-85`、`ModPage.cpp:157-166` | 服务端 `getModCategories()` 拉回后 `setCategories()` |

PCL-CE 的中文生态补充：`pclce:Plain Craft Launcher 2/Pages/PageDownload/Comp/PageComp.xaml:33-106`
有「来源 / Tags / 排序 / 版本 / 加载器」五组；分类映射写在
`pclce:…/PageDownloadMod.xaml:10-53`，形如 `Tag="406/worldgen"`（前段 CF `categoryId`、
后段 MR category slug），**一套控件同时喂两个源**。

- **AC 落地点**：新增 `src/store_filter.py`（`StoreFilterPanel`），字段严格取上表；
  分类沿用 `STORE_CATEGORIES`，映射表按 `PageDownloadMod.xaml` 的双段 tag 格式。
- **断言点**：筛选字段集合与上游一致；改动任一筛选项会 `emit filterChanged` 且触发一次重新搜索
  （不重复请求，见 §2.7 请求去重）。

### 2.3 版本 / 加载器 / 分类过滤全部下推服务端

**上游证据 A（CF）** `prism:launcher/modplatform/flame/FlameAPI.cpp:267-296`

```cpp
getArguments.append(QString("classId=%1").arg(getClassId(args.type)));
getArguments.append(QString("index=%1").arg(args.offset));
getArguments.append("pageSize=25");
if (args.search.has_value()) getArguments.append(QString("searchFilter=%1").arg(args.search.value()));
if (args.sorting.has_value()) getArguments.append(QString("sortField=%1").arg(args.sorting.value().index));
getArguments.append("sortOrder=desc");
if (args.loaders.has_value()) { … "modLoaderTypes=%1" … }
if (args.categoryIds.has_value() …) { … "categoryIds=[%1]" … }
if (args.versions.has_value() …) { … "gameVersion=%1" … }
return BuildConfig.FLAME_BASE_URL + "/mods/search?gameId=432&" + getArguments.join('&');
```

**上游证据 B（HMCL，同一口径）** `hmcl:HMCLCore/…/CurseForgeRemoteAddonRepository.java:112-122`

```java
query.put("gameId", "432");
query.put("classId", Integer.toString(section));
if (categoryId != 0) query.put("categoryId", Integer.toString(categoryId));
query.put("gameVersion", gameVersion);
query.put("searchFilter", searchFilter);
query.put("sortField", Integer.toString(toModsSearchSortField(sortType)));
query.put("sortOrder", toSortOrder(sortOrder));
query.put("index", Integer.toString(pageOffset * pageSize));
query.put("pageSize", Integer.toString(pageSize));
```

注释明确写着 `/// Searches the configured section, preserving the order returned by the server.`（`:96`）——
**不把结果拉回本地重排**。

**上游证据 C（MR facets）** `prism:launcher/modplatform/modrinth/ModrinthAPI.cpp:105-144` 与 `:342-356`

```cpp
facetsList.append(QString("[%1]").arg(loaders));     // categories:<loader>
facetsList.append(QString("[%1]").arg(versions));    // versions:<mc>
facetsList.append(QString(R"(["categories:%1"])").arg(category));
facetsList.append(QString("[\"project_type:%1\"]").arg(...));
return BuildConfig.MODRINTH_PROD_URL + "/search?offset=…&limit=25&query=…&index=…&facets=…";
```

HMCL 同构：`hmcl:…/ModrinthRemoteAddonRepository.java:149-163`（`project_type` / `versions` /
`categories` 三段 facets + `offset=pageOffset*pageSize` + `limit` + `index` 排序）。

**AC 现状差距**：`src/net_api.py:1564-1572` 的 `_cf_page()` 只有
`gameId/classId/searchFilter/pageSize/index/sortField/sortOrder`，**缺 `gameVersion` /
`modLoaderType(s)` / `categoryId`**；`src/net_api.py:2579` 的 `search_mods()` 只按 `project_type`
过滤，无版本/加载器 facets。版本过滤目前发生在详情页拉回文件列表之后。

- **AC 落地点**：`_cf_page()` / `search_curseforge()` / `search_mods()` 统一新增可选
  `game_version`、`loader`、`category_id`、`sort` 形参；`search_all()` 透传；
  `StorePage._load()` 从 `_target()`（`src/pages_browse.py:599-628`）取目标实例的 MC 版本与加载器。
- **断言点**：构造出的 URL 参数与上游四段一一对应；**不得**出现「拉回 N 条再本地筛」的
  `_cf_pool` 式回退（round-207 已废弃，见 `net_api.py:1551-1562` 的注释）。

### 2.4 排序映射（不再写死一个数字）

**上游证据** `pclce:PCL.Launcher.Core/Comp/ProjectRequest.cs:137-146`（CF）与 `:165-173`（MR）

```csharp
var sortField = sort switch {
    CompSortType.Relevance => "4",  CompSortType.Downloads => "6",
    CompSortType.Follows   => "2",  CompSortType.Newest    => "11",
    CompSortType.Updated   => "3",  _ => "2"
};
// Modrinth
var index = sort switch {
    CompSortType.Downloads => "downloads", CompSortType.Follows => "follows",
    CompSortType.Newest => "newest", CompSortType.Updated => "updated",
    _ => "relevance"
};
```

Prism 则由 API 自身声明可用排序：`prism:launcher/modplatform/ResourceAPI.h:108-109`
`virtual auto getSortingMethods() const -> QList<SortingMethod> = 0;`，UI 只填
`sortByBox`（`ResourcePage.cpp:199-210`）。

> ⚠ **复核纪律（§十四）**：round-207 已在**我们实际使用的 MCIM 镜像**上实测
> `sortField=1&sortOrder=desc` 让 `sodium` 排第 1（推翻 round-141 的旧结论）。
> PCL-CE 的 `Relevance=>4` 是官方 `api.curseforge.com` 的取值，**不能直接套到镜像**。
> 落地时保留 `1` 为默认值，另做一次六档对照实验再决定映射表；实验前不删默认值。

- **AC 落地点**：`src/net_api.py` 新增 `STORE_SORTS` 常量与 `_cf_sort_field()` / `_mr_sort_index()`；
  `StorePage` 侧栏加排序下拉。
- **断言点**：默认排序仍是 round-207 实测值；每档排序都映射到一个非空服务端参数；
  排序变化必须让缓存 key 变化（否则换排序不生效）。

### 2.5 双源各自 offset / total 游标（关键状态机）

**上游证据** `pclce:PCL.Launcher.Core/Comp/ProjectStorage.cs:5-22`

```csharp
public int curseForgeOffset;  public int curseForgeTotal = -1;
public int modrinthOffset;    public int modrinthTotal = -1;
public List<CompProject> results = [];  public string? errorMessage = null;
```

`pclce:…/ProjectRequest.cs:77-91` 的 `CanContinue` 按 `offset < total` 判定是否继续；
`pclce:…/ProjectQuery.cs:649-651` / `:680-681` 在每页回来后**按实际条数推进 offset**、
从 `pagination.totalCount` / `total_hits` 读 total：

```csharp
storage.curseForgeOffset += projects.Count;
storage.curseForgeTotal  = json["pagination"]?["totalCount"]?.ToObject<int>() ?? 0;
storage.modrinthOffset  += projects.Count;
storage.modrinthTotal    = json["total_hits"]?.ToObject<int>() ?? 0;
```

HMCL 同样用 total 算总页数：`hmcl:…/CurseForgeRemoteAddonRepository.java:92-94`
`ceil(min(totalCount, 10000) / pageSize)`；MR 侧 `:172` `ceil(total_hits / pageSize)`。
Prism 则用 `prism:…/ResourceModel.cpp:455-460` 的「本页条数 < 25 → Finished，否则 offset += 25」。

- **AC 现状差距**：`src/pages_browse.py:410,416` 只有**一个** `self._offset` 和一个
  `self._has_more`，双源翻页共用同一把尺子；源 A 先到 / 源 B 迟到时会错位。
- **AC 落地点**：`src/net_api.py` 的 `search_all()` 返回结构升级为带双源游标（或新增
  `search_all_paged()`），`StorePage` 用 `{mr:{offset,total}, cf:{offset,total}}` 管状态。
- **断言点**：两源各自推进、互不覆盖；`total` 到顶后不再发请求；单源失败不影响另一源游标。

### 2.6 分页模型 — **待拍板，见 §4-A**

Prism：`prism:…/ResourceModel.cpp:162-169` `fetchMore()` → `search()`，
`:435-470` 到手即 `beginInsertRows` 增量 append；`prism:…/modrinth/ModrinthModel.cpp:81-91`
明确拒绝 `offset == 0` 的 `fetchMore`（防重复首页）。
PCL-CE：`pclce:…/PageComp.xaml.cs:15` `PageSize = 40`、`:34-48` 按页切片、
`:295-297` `targetResultCount = (page + 1) * PageSize`；
`pclce:…/PageCompViewModel.cs:55-69` 页码器依据双源 `offset < total` 决定可否翻页。
**两家相反**，不能同时「99% 对齐」，必须由主理人选一个（§4-A）。

### 2.7 搜索防抖与请求去重

**上游证据** `prism:launcher/ui/pages/modplatform/ResourcePage.cpp:95-105`

```cpp
m_searchTimer.setTimerType(Qt::TimerType::CoarseTimer);
m_searchTimer.setSingleShot(true);
connect(&m_searchTimer, &QTimer::timeout, this, &ResourcePage::triggerSearch);
connect(m_ui->searchEdit, &QLineEdit::textEdited, this, [this] {
    if (m_searchTimer.isActive()) m_searchTimer.stop();
    m_searchTimer.start(350);
});
```

筛选变化触发重搜前会清空选中/详情/版本框：`prism:…/ModPage.cpp:130-147`。
PCL-CE 侧用请求对象做去重：`pclce:…/ProjectRequest.cs:196-209` 的 `Equals` 比较
`type / targetResultCount / tag / modLoader / source / gameVersion / searchText / sort` 八字段。

- **AC 现状**：`src/pages_browse.py:425-428` 已有 180ms 防抖（比 Prism 更急），
  `:518` 有 `_load_gen` 旧结果守卫；**缺筛选条件变化时的请求去重**。
- **AC 落地点**：防抖改 350ms（对齐 Prism）；新增 `_request_key()` 与 `_load_gen` 联合判重。
- **断言点**：连续输入只发一次请求；同样筛选条件下重复触发不产生第二次 HTTP；
  旧 gen 的结果即使迟到也不覆盖新页（`round-207` 的 `sourcePartial` 守卫保留）。

### 2.8 图标占位先行 / 视口懒加载 / 缓存

**上游证据** `prism:launcher/ui/pages/modplatform/modrinth/ModrinthModel.cpp:111-119`

```cpp
case Qt::DecorationRole: {
    if (m_logoMap.contains(pack->logoName)) return m_logoMap.value(pack->logoName);
    QIcon icon = QIcon::fromTheme("screenshot-placeholder");   // 先给占位
    const_cast<ModpackListModel*>(this)->requestLogo(pack->logoName, pack->logoUrl);
    return icon;
}
```

`prism:…/ResourceModel.cpp:385-431` 的 `getIcon()`：`QPixmapCache::find()` 命中立即返回；
`m_currentlyRunningIconActions` / `m_failedIconActions` 两个集合去重；落盘用
`metacache()->resolveEntry(..., "logos/<sha1(url)>")`；成功后只 `emit dataChanged(index, index,
{Qt::DecorationRole})` —— **不重建整张卡片**。

- **AC 现状**：`src/async_image.py` 已有 6 并发 / 512KB 熔断 / 失败负缓存 / 磁盘缓存，
  但 `src/pages_browse.py:838` 的 `_make_card()` 是「字先出、图后冒」，没有占位图立即上屏，
  也没有「仅视口内才 load」。
- **AC 落地点**：`_make_card()` 先 `setPixmap(_letter_fallback(...))`（该函数已存在，
  `src/pages_browse.py:73`）；`ImageLoader.load()` 只在卡片进入视口后调用；成功只替换该卡图标。
- **断言点**：无网络时首屏卡片仍有图标位；同一 URL 不重复请求；图标回来不重建卡片对象。

### 2.9 缓存：stale-while-revalidate + 条件请求

**上游证据** `pclce:PCL.Core/IO/Net/Http/Cache/HttpCacheHandler.cs:23-99`

```csharp
var cached = await _cacheService.GetAsync<byte[]>(cacheKey, ct);
if (cached.Found) { … "X-Cache-Hit: HIT" … return cachedResponse; }
// 未命中：带 ETag / Last-Modified 发条件请求
if (response.StatusCode is HttpStatusCode.NotModified) { /* 复用旧 body */ }
var ttl = _ComputeTtl(response);   // Cache-Control MaxAge / SharedMaxAge / 默认 5 分钟
await _cacheService.SetAsync(cacheKey, body, new CachePolicy{ AbsoluteExpiration = ttl, … });
```

- **AC 现状**：`src/net_api.py:66-71,134-159` 是纯 TTL（内存 30min / 磁盘 24h / max age 7d），
  `_stale()` 存在但只有过期兜底，没有「先画旧数据 + 后台刷新」。
- **AC 落地点**：`_cached()` 新增 `allow_stale=True` 出参（命中但过期时返回 `(value, is_stale)`），
  `StorePage._on_loaded()` 对 stale 结果显示「正在更新」并在后台刷新完成后局部替换。
- **断言点**：过期缓存存在时首帧渲染**不等待网络**；刷新失败保留旧数据并提示，不清空页面。

### 2.10 详情页：同屏、版本/前置预取

- `prism:…/ResourcePage.cpp:223-306` `updateUi(index)` 在选中项变化时更新第三格详情；
  `:333-357` `refreshVersionComboBox()` 与 `:381-441` `versionListUpdated()` 拉版本；
  `prism:…/ResourceDownloadDialog.cpp:391-398` 依据实例加载器决定哪些源可用。
- `pclce:…/PageDownloadCompDetail.xaml` 是独立详情页（**不是抽屉**），
  `pclce:PCL.Core/Minecraft/ResourceProject/ModDependencyResolver.cs` 负责前置依赖。
- **AC 现状**：`src/pages_browse.py:984-1014` 用 `_stack` 整页切到 `src/store_detail.py`；
  版本 / 前置 / 中文简介在点开后串行请求。
- **AC 落地点**：详情改第三格（§2.1）；`store_detail.py` 的 `StoreDetailPanel` 保持
  `QWidget` 以便嵌入；对可见卡片预取版本列表（限 3 条，避免请求风暴）。
- **断言点**：选中卡片不改变页面栈；预取并发有上限；详情面板可独立构造（页内/窗口两态同实现）。

### 2.11 徽章与列表字段

`pclce:…/MyCompItemViewModel.cs:26-48` 的卡片 VM 字段：
`SourceText` / `ShowVersion` / `ShowTime` / `ShowFavoriteButton` / `ShowDownloadButton` /
`VersionText` / `TimeText` / `DownloadText`；`pclce:…/PageCompViewModel.cs:77-81`
`ReplaceProjects()` 强调「整体替换，只触发一次集合变更通知」。
`prism:…/ModFilterWidget.ui:255-257` 的「Hide installed items」与
`prism:…/ResourceModel.cpp:46-76` 的 `isPackInstalled()` / `getInstalledPackVersion()` 联动。

- **AC 落地点**：`src/pages_browse.py:838-935` `_make_card()` 统一「来源 / 兼容 / 已装 / 下载量」徽章；
  `_compat_of_card()`（`:961`）与 `_is_installed()`（`:945`）复用现有判定，不另写一套。
- **断言点**：列表页能读出「已装」；徽章口径与详情页一致（不能列表说兼容、详情说不兼容）。

### 2.12 中文搜索与错误/部分结果

- `pclce:…/ProjectQuery.cs:212-227` 中文搜索走 `_ApplyChineseSearch()` 名库反查，
  并单独维护 `curseForgeAltSearchText`（注释见 `ProjectRequest.cs:10-13`：
  CF 有任意关键词未匹配就不返回结果，所以不能用与 MR 相同的词）。
- `pclce:…/ProjectQuery.cs:193-201` 无结果时抛 `Download.Comp.List.NoMatchingResults`；
  `:655-658` / `:684-688` 单源失败各自记日志、返回异常对象，**不拖死另一源**。
- **AC 现状**：`src/net_api.py:1451` `_cf_search_zh()` 已有名库反查；
  `search_all()` 的 `meta.partial` + `store.partial` 文案（round-206/207）已有，
  语义与上游一致，**这条基本已对齐，只需保持**。
- **断言点**：中文词仍能搜到；单源超时显示「部分结果」而不是空白页。

---

## 3. AC 现状差距清单（`file:line` 精度）

| # | 差距 | 现状位置 | 对应规格 |
|---|---|---|---|
| 1 | 无筛选侧栏，详情整页切走 | `src/pages_browse.py:433-529`、`:984-1014` | §2.1 / §2.10 |
| 2 | CF 请求缺版本/加载器/分类参数 | `src/net_api.py:1564-1572` | §2.3 |
| 3 | MR 请求缺版本/加载器 facets | `src/net_api.py:2579` | §2.3 |
| 4 | 排序写死 `sortField=1` | `src/net_api.py:1570` | §2.4 |
| 5 | 双源共用一个 `offset` / `has_more` | `src/pages_browse.py:410,416,682` | §2.5 / §2.6 |
| 6 | 无限滚动，无页码器 | `src/pages_browse.py:535-537,671-687` | §2.6 |
| 7 | 防抖 180ms，无筛选请求去重 | `src/pages_browse.py:425-428` | §2.7 |
| 8 | 卡片无占位图、无视口懒加载 | `src/pages_browse.py:838` | §2.8 |
| 9 | 缓存过期即等网络，无 SWR / 条件请求 | `src/net_api.py:134-159` | §2.9 |
| 10 | 徽章字段不全（已装只在详情） | `src/pages_browse.py:945,961` | §2.11 |
| 11 | IA 路径表仍是「假护栏」（3 页 / 21 条） | `docs/ia/paths.md`、`tests/check_paths.py` | §5 |

---

## 4. 需要主理人拍板的 3 个分歧（**拍板前不动 UI 源码**）

| 分歧 | 选项 A（上游代码） | 选项 B（上游代码） | 默认建议 |
|---|---|---|---|
| **A. 分页模式** | Prism 无限滚动：`ResourceModel.cpp:162-169,435-470`、`ModrinthModel.cpp:81-91` | PCL-CE 真页码器：`PageComp.xaml.cs:15,34-48`、`PageCompViewModel.cs:55-69` | **B**：§十四 P0-3 明确写了「真分页」，且双源游标（§2.5）天然适合页码器；代价是放弃 round-207 刚做的无限滚动增量 append |
| **B. 默认来源** | §十四 P0-2 建议「默认单源 + 显式切换」 | round-140 主理人拍板「默认全部双源」 | **保持 B**：round-140 是明确拍板，不为了像别人悄悄改；只在侧栏把「来源」提升为一级控件 |
| **C. 详情形态** | Prism 第三栏抽屉（同屏） | PCL-CE 独立详情页 / AC 现状整页栈 | **A**：用户最初吐槽「功能相同却页面不一样」「不要不断开窗口」，第三栏最贴合整页重做的目标 |

> 这三条决定 `src/pages_browse.py` 的骨架写法，改错要整页返工，因此先问再写。
> A/B/C 之外的 12 条规格无分歧，拍板后按 §5 直接落地。

---

## 5. 落地映射表（Task #354 用）

| 文件 | 改动 | 规格条目 |
|---|---|---|
| `src/store_filter.py`（新增） | `StoreFilterPanel(QWidget)`：筛选字段 / `filterChanged` / `get_filter()` | §2.1 / §2.2 |
| `src/pages_browse.py` | `QSplitter` 三栏、页码器或无限滚动、双源游标、350ms 防抖、占位图、SWR 状态、徽章 | §2.1 / §2.5-2.11 |
| `src/net_api.py` | `_cf_page()` / `search_mods()` 增服务端过滤与排序参数；`search_all()` 出参带双源游标；`_cached(allow_stale=True)` | §2.3-2.5 / §2.9 |
| `src/async_image.py` | 视口内才 `load()`；成功只换图标不重建卡片 | §2.8 |
| `src/store_detail.py` | `StoreDetailPanel` 可嵌第三格；可见卡片预取（限 3） | §2.10 |
| `src/i18n.py` | 新增筛选 / 排序 / 分页 / SWR 文案，中英对称 | §2.2 / §2.6 / §2.9 |
| `docs/ia/paths.md` + `tools/gen_paths.py` + `tests/check_paths.py` | 补资源中心路径与**覆盖率断言**（修「假护栏」） | §3-11 |
| `regress.py` + `tests/test_round208_store_alignment.py` | §6 的断言 | 全部 |

---

## 6. 回归断言清单（每项一条，沿用 round-206/207 做法）

1. 三栏 `QSplitter.count() == 3`；详情不切栈。
2. 筛选字段集合与 §2.2 表格一致，且 `filterChanged` 触发恰好一次重搜。
3. CF 请求参数含 `gameVersion` / `modLoaderType(s)` / `categoryId` / `sortField` / `index` / `pageSize`。
4. MR 请求 `facets` 含 `versions` / `categories` / `project_type`，`offset` 与 `limit` 成对。
5. 无 `_cf_pool` / 本地 N 条重排回退；保持一次搜索一次请求。
6. 排序每档映射到非空服务端参数，且排序进入缓存 key。
7. 双源 `{offset,total}` 各自推进；到顶不发请求；单源失败不影响另一源。
8. 分页模式与拍板结果一致（页码器状态机或 `fetchMore` 状态机，二选一断言）。
9. 防抖 350ms；相同筛选不重复发请求；旧 gen 迟到结果被丢弃。
10. 占位图立即上屏；同 URL 不重复请求；图标回来不重建卡片。
11. 过期缓存存在时首帧不等网络；刷新失败保留旧数据。
12. 列表页「已装 / 不兼容」徽章口径与详情一致。
13. 中文搜索仍命中；单源超时显示 `store.partial`，不空白。
14. i18n 中英键集合对称；IA 路径表覆盖率达标。
15. 默认来源仍是 `all`（防止悄悄改 round-140 决策）。
16. `regress.py` 全绿、`_pii_gate.py` zero、页面构造冒烟通过。

---

## 7. 明确不做（防止范围蔓延）

- ❌ 不换后端：官方 CF key / 国内聚合 API 属 §十四 P2，需主理人授权，本轮默认镜像行为不动。
- ❌ 不复制上游源码文本，只对齐行为与参数（§0.4）。
- ❌ 不把 PCL-CE 的 `sortField` 取值直接套到 MCIM 镜像（§2.4 复核纪律）。
- ❌ 不改 `Worker` / `TrackedThread` / 打包链路；不碰 `D:\Appdata\AC_Launcher` 直到 Task #356。
- ❌ 不因为「像别人」推翻主理人已拍板的 round-140 默认源与 round-207 实测排序值。
