# round-208 — 资源中心「99% 代码级对齐」对照规格

> **决策来源**：主理人「这样，我们直接仿照其他启动器学一遍吧」→ 选择「整套对齐含整页重做」→ 追加
> 「注意是 99% 的代码参考学习」。
> **本文件性质**：Task #353 的交付物。逐条写清「上游怎么做（含 `repo:path:line` 与代码片段）→
> AC 落到哪个文件/函数 → 用哪条回归断言证明落地」。
> **状态**：2026-11-07 主理人拍板 3 个 IA 分歧（§4）；**2026-11-08 阶段二已按拍板落地**
> （数据层 + 整页重做 + IA 护栏，回归 77/77），落地清单与新增偏离见 §4.1。
> **拍板结果与推荐项不一致处以拍板为准**。
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
按主理人拍板，本规格采用 **筛选侧栏 / 结果区两栏 + 详情保留整页切换 + PCL-CE 页码器与
双源游标 + HMCL/Prism 的 URL 参数**，即 §2 的 12 条。详见 §4。
> ⚠ 上游 Prism 是三栏（详情也在同屏），主理人明确选择**保留现有整页切换**，
> 因此本轮的「整页重做」= 筛选侧栏 + 结果区 + 页码器 + 卡片/徽章/缓存重做，
> **详情形态不动**（这正是 1% 偏离之一，登记在 §0.3）。

---

## 2. 逐条对照规格

### 2.1 两栏骨架（筛选 / 结果同屏，详情保留整页切换）

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

- **AC 落地点**：`src/pages_browse.py:433-529` 的 `StorePage` 根布局 → 换成 `QSplitter`，
  两格 = `StoreFilterPanel` / 结果区（列表 + 页码器）。筛选面板复用 Prism 的
  `replaceWidget` 可折叠思路；**`self._stack`（`:527-529`）保留**，详情继续整页切换。
- **断言点**：`StorePage` 存在 `QSplitter` 且 `count() == 2`；`_open_detail()` 仍切
  `QStackedWidget` 到详情、`_close_detail()` 切回列表，**不新开窗口 / 不新建 QDialog**。

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
  `StorePage._load()` 只取**侧栏显式筛选**（round-209 修订，见下）。
- **断言点**：构造出的 URL 参数与上游四段一一对应；**不得**出现「拉回 N 条再本地筛」的
  `_cf_pool` 式回退（round-207 已废弃，见 `net_api.py:1551-1562` 的注释）；
  **默认请求不得携带 `gameVersion` / `modLoaderType`**（round-209 回归红线）。

> **round-209 修订（规格纠错，2026-11-08）**：本条初版写了「`_load()` 从
> `_target()` 取目标实例的 MC 版本与加载器」，落地成「玩家什么都没选也按当前
> 实例静默收窄搜索」。这是对上游的误读 —— `prism:ModFilterWidget.ui:198-224`
> 与 `pclce:PageComp.xaml:33-106` 的版本 / 加载器**都是玩家显式选的**，上游没有
> 「按当前实例偷偷过滤」这回事；HMCL 的 `gameVersion` 同样来自 `args.versions`。
> 联网 A/B 实测：CF「FTB」409 → 58 条（-86%）、「FTB Quests」140 → 27 条且
> `can_next=False`，FTB 官方 Forge/NeoForge 版本整批消失（主理人当日报「一部分
> mod 搜不到」）。
> **现行口径**：`_collect_filters()` 只取侧栏值；`set_target()` 只用 editable
> combo 的 `setPlaceholderText()` 给提示，不产生真实筛选；版本 / 加载器继续用于
> 详情页推荐版本与卡片兼容性徽章。断言见 `tests/test_round209_store_regression.py`。

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

### 2.6 分页模型 — **已拍板：真页码器（PCL-CE 口径）**

Prism：`prism:…/ResourceModel.cpp:162-169` `fetchMore()` → `search()`，
`:435-470` 到手即 `beginInsertRows` 增量 append；`prism:…/modrinth/ModrinthModel.cpp:81-91`
明确拒绝 `offset == 0` 的 `fetchMore`（防重复首页）。
PCL-CE：`pclce:…/PageComp.xaml.cs:15` `PageSize = 40`、`:34-48` 按页切片、
`:295-297` `targetResultCount = (page + 1) * PageSize`；
`pclce:…/PageCompViewModel.cs:55-69` 页码器依据双源 `offset < total` 决定可否翻页。
**拍板结果：采用 B（PCL-CE 真页码器）**。落地 `PageSize=40` 口径、
`targetResultCount=(page+1)*PageSize`、双源 `offset<total` 决定可否翻页、
`ReplaceProjects()` 整体替换只触发一次布局。round-207 的 **按源渐进渲染保留**：
它负责「同一页内两源先后到达时的首屏出卡」，与页码器不冲突；被替换的只是
无限滚动 `_more()` / `_has_more` 闸门。

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

### 2.10 详情页：保留整页切换、版本/前置预取

- `prism:…/ResourcePage.cpp:223-306` `updateUi(index)` 在选中项变化时更新第三格详情；
  `:333-357` `refreshVersionComboBox()` 与 `:381-441` `versionListUpdated()` 拉版本；
  `prism:…/ResourceDownloadDialog.cpp:391-398` 依据实例加载器决定哪些源可用。
- `pclce:…/PageDownloadCompDetail.xaml` 是独立详情页（**不是抽屉**），
  `pclce:PCL.Core/Minecraft/ResourceProject/ModDependencyResolver.cs` 负责前置依赖。
- **AC 现状**：`src/pages_browse.py:984-1014` 用 `_stack` 整页切到 `src/store_detail.py`；
  版本 / 前置 / 中文简介在点开后串行请求。
- **AC 落地点**：**详情形态不动**（主理人拍板），`self._stack` 继续承载
  「列表 ↔ 详情」整页切换；`store_detail.py` 的 `StoreDetailPanel` 保持 `QWidget`；
  只补「可见卡片预取版本列表（限 3 条）」以降低点开后的串行等待。
- **断言点**：选中卡片切到详情、返回回列表，全程不新开窗口；预取并发有上限；
  详情面板可独立构造（页内 / 窗口两态同实现）。

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
| 1 | 无筛选侧栏（**详情整页切换是主理人保留项，不算差距**） | `src/pages_browse.py:433-529` | §2.1 / §2.10 |
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

## 4. 主理人拍板结果（2026-11-07，已定）

| 分歧 | 拍板 | 依据 / 影响 |
|---|---|---|
| **A. 分页模式** | ✅ **真页码器（PCL-CE）** | 与 §十四 P0-3「真分页」一致；双源 `offset/total` 游标天然适配。代价：替换 round-207 的无限滚动 `_more()` 闸门，但按源渐进渲染保留 |
| **B. 详情形态** | ✅ **保留整页切换**（**否决了推荐的三栏同屏**） | 主理人选择现有 `_stack` 列表↔详情整页切换；不开窗口、不新建 QDialog。骨架因此是**两栏**而非三栏 |
| **C. 默认来源** | ✅ **保持「全部」双源** | 维持 round-140 拍板；只把「来源」提升为筛选侧栏一级控件，不悄悄改后端 |

> 拍板后 §2.1 / §2.6 / §2.10 / §3 / §5 / §6 / §7 已全部按结果修订。
> 规格与推荐项冲突处一律以本表为准；阶段二（Task #354）直接按此实现，不再二次确认。

### 4.1 阶段二落地结果（2026-11-08）

| 规格条目 | 落地文件 | 回归断言 |
|---|---|---|
| §2.1 两栏骨架 | `src/pages_browse.py` `StorePage.splitter` | 对齐测试 [1][6] |
| §2.2 筛选侧栏 | `src/store_filter.py`（新增，上游真实 27 tag / 12 版本 / loader 枚举） | 对齐测试 [3][6] |
| §2.3 服务端过滤 | `src/store_search.py`（新增，不动 `net_api.py`） | 数据层测试 [2][3][4] |
| §2.4 排序映射 | `src/store_search.py` `_CF_SORT_FIELD` / `_MR_SORT_INDEX` | 数据层测试 [1][2] |
| §2.5 双源游标 | `src/store_search.py` `new_store_cursors` / `store_can_continue` | 数据层测试 [6][7] |
| §2.6 真页码器 | `src/pages_browse.py` `_build_pager` / `_goto_page` / `_update_pager` | 对齐测试 [2][6] |
| §2.7 防抖去重 | `src/pages_browse.py` 350ms + `_request_key` + `gen` | 对齐测试 [4][6] |
| §2.8 占位 / 懒加载 | `src/pages_browse.py` `_make_card` + `_pump_icons` | 对齐测试 [4][6] |
| §2.9 SWR | `store_search.cache_lookup` + UI `_swr_cache` | 数据层测试 [5] / 对齐测试 [4][6] |
| §2.10 详情整页切换 | `self._stack` 保留，不新开窗口 | 对齐测试 [1][6] |
| §2.11 徽章 | `_make_card` 复用 `_is_installed` / `_compat_of_card` | 对齐测试 [4] |
| §2.12 中文 / 部分结果 | 保持 round-206/207 语义 | 对齐测试 [4] |
| §3-11 IA 假护栏 | `tools/gen_paths.py` + `docs/ia/paths.md`（4 页 / 29 条） | 对齐测试 [5] |

**1% 偏离增补（阶段二实测后登记）**：

- 上游 `prism:ModFilterWidget.ui:226-296` 的发布渠道 / 运行环境 / 仅开源三项，
  AC 数据层无对应字段（MR search hits 无 channel / open_source）→ **不渲染摆设控件**，
  登记在 `docs/quality_punchlist.md` §十四。
- 「详情页预取版本列表」与「搜索 / 详情共用一份项目缓存」未做，属 §十四 P1。
- 视口懒加载用「视口 ±120/240px 泵」实现，未移植 Qt `dataChanged` 机制
  （沿用 AC 既有 `ImageLoader`，属 §0.3 第 4 类偏离）。

## 5. 落地映射表（Task #354 用）

| 文件 | 改动 | 规格条目 |
|---|---|---|
| `src/store_filter.py`（新增） | `StoreFilterPanel(QWidget)`：筛选字段 / `filterChanged` / `get_filter()` | §2.1 / §2.2 |
| `src/pages_browse.py` | `QSplitter` 两栏（筛选 / 结果）、**真页码器**、双源游标、350ms 防抖、占位图、SWR 状态、徽章；详情保留 `_stack` | §2.1 / §2.5-2.11 |
| `src/net_api.py` | `_cf_page()` / `search_mods()` 增服务端过滤与排序参数；`search_all()` 出参带双源游标；`_cached(allow_stale=True)` | §2.3-2.5 / §2.9 |
| `src/async_image.py` | 视口内才 `load()`；成功只换图标不重建卡片 | §2.8 |
| `src/store_detail.py` | `StoreDetailPanel` 可嵌第三格；可见卡片预取（限 3） | §2.10 |
| `src/i18n.py` | 新增筛选 / 排序 / 分页 / SWR 文案，中英对称 | §2.2 / §2.6 / §2.9 |
| `docs/ia/paths.md` + `tools/gen_paths.py` + `tests/check_paths.py` | 补资源中心路径与**覆盖率断言**（修「假护栏」） | §3-11 |
| `regress.py` + `tests/test_round208_store_alignment.py` | §6 的断言 | 全部 |

---

## 6. 回归断言清单（每项一条，沿用 round-206/207 做法）

1. 两栏 `QSplitter.count() == 2`；详情仍走 `_stack` 整页切换且不新开窗口。
2. 筛选字段集合与 §2.2 表格一致，且 `filterChanged` 触发恰好一次重搜。
3. CF 请求参数含 `gameVersion` / `modLoaderType(s)` / `categoryId` / `sortField` / `index` / `pageSize`。
4. MR 请求 `facets` 含 `versions` / `categories` / `project_type`，`offset` 与 `limit` 成对。
5. 无 `_cf_pool` / 本地 N 条重排回退；保持一次搜索一次请求。
6. 排序每档映射到非空服务端参数，且排序进入缓存 key。
7. 双源 `{offset,total}` 各自推进；到顶不发请求；单源失败不影响另一源。
8. 真页码器：页码 / 上一页 / 下一页 / 首页状态由双源 `offset<total` 推导；不再有 `_more()` / `_has_more` 无限滚动触发。
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
- ❌ **不把详情改成 Prism 式第三栏**：主理人 2026-11-07 明确选择保留整页切换。
