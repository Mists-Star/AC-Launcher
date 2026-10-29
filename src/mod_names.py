"""Mod 中文名映射（round-45，学主流启动器的显示中文名做法）。

Modrinth API 不返回项目中文名（Accept-Language 只影响平台 UI 不影响
title/description）。这里维护一份「slug → 展示名」内置表（覆盖热门常用
mod / 整合包 / 光影 / 资源包），资源中心/依赖树显示时统一为
「英文原名（中文翻译）」格式，英文在前、中文在后；未收录的显示原文。

round-128：表中的 slug 已全部对 Modrinth 真接口验证（不存在的已剔除，
拼错的已改成真实 slug），并补齐热门整合包/光影/资源包——这是「搜中文能
搜到」和「卡片显示中文名」的唯一数据源（Modrinth 搜索本身不认中文）。

如何扩充：往 _MOD_CN 里加 slug 与展示名即可（slug = Modrinth project
slug）。格式统一：English Name（中文说明），中文部分用「·」分隔备注。
"""

_MOD_CN = {
    # ── 渲染 / 优化 ──
    "sodium": "Sodium（钠·渲染优化）",
    "sodium-extra": "Sodium Extra（Sodium 附加）",
    "iris": "Iris（虹彩·光影加载器）",
    "oculus": "Oculus（光影加载）",
    "lithium": "Lithium（锂·逻辑优化）",
    "phosphor": "Phosphor（磷·光照优化）",
    "krypton": "Krypton（氪·网络优化）",
    "ferrite-core": "FerriteCore（铁氧体核心·内存优化）",
    "lazydfu": "LazyDFU（懒加载 DFU）",
    "smoothboot-fabric": "Smooth Boot（并行加载）",
    "entityculling": "Entity Culling（实体剔除）",
    "moreculling": "More Culling（更多剔除）",
    "immediatelyfast": "ImmediatelyFast（立即快速·渲染优化）",
    "reeses-sodium-options": "Reese's Sodium Options（Reese 的 Sodium 设置）",
    "canary": "Canary（金丝雀·优化）",
    "modernfix": "ModernFix（现代修复·启动优化）",
    "badoptimizations": "BadOptimizations（深度优化）",
    "indium": "Indium（铟·Sodium 渲染兼容）",
    "noisium": "Noisium（噪声优化）",
    # ── 物品栏 / 信息 ──
    "jei": "Just Enough Items（JEI 物品栏）",
    "emi": "EMI（物品管理）",
    "wthit": "WTHIT（看向什么）",
    "jade": "Jade（方块信息）",
    "hwyla": "HWYLA（方块信息）",
    "wawla": "WAWLA",
    "appleskin": "AppleSkin（苹果皮·饱食度显示）",
    "neat": "Neat（血条）",
    "xaeros-minimap": "Xaero's Minimap（Xaero 小地图）",
    "xaeros-world-map": "Xaero's World Map（Xaero 世界地图）",
    "journeymap": "JourneyMap（旅行地图）",
    "betterf3": "BetterF3（更好的 F3）",
    "fpsdisplay": "FPS Display（FPS 显示）",
    # ── 核心 / 前置 ──
    "fabric-api": "Fabric API",
    "fabric-language-kotlin": "Fabric Language Kotlin（Kotlin 语言包）",
    "architectury-api": "Architectury API",
    "cloth-config": "Cloth Config（配置库）",
    "yacl": "YACL（YetAnotherConfigLib 配置库）",
    "balm": "Balm",
    "geckolib": "GeckoLib（动画库）",
    "playeranimator": "Player Animator（玩家动画）",
    "owo-lib": "owo-lib",
    "trinkets": "Trinkets（饰品）",
    "curios": "Curios API（饰品栏）",
    "cardinal-components-api": "Cardinal Components（数据组件库）",
    "epic-libs": "Epic Libs（库）",
    # ── 玩法 ──
    "create": "Create（机械动力）",
    "tweakeroo": "Tweakeroo（辅助微调）",
    "malilib": "MaLiLib（库）",
    "litematica": "Litematica（投影）",
    "schematica": "Schematica（旧版投影）",
    "minihud": "MiniHUD（迷你 HUD）",
    "simple-voice-chat": "Simple Voice Chat（简单语音聊天）",
    "modmenu": "Mod Menu（模组菜单）",
    "inventory-profiles-next": "Inventory Profiles Next（背包整理）",
    "puzzle": "Puzzle（渲染兼容）",
    "controlling": "Controlling（按键绑定管理）",
    "mouse-tweaks": "Mouse Tweaks（鼠标微调）",
    "default-options": "Default Options（默认选项）",
    "dynamic-fps": "Dynamic FPS（动态帧率·挂机降帧）",
    "borderless-mining": "Borderless Mining（无边框全屏）",
    "spark": "Spark（性能分析）",
    "essential": "Essential（联机助手）",
    "lambdynamiclights": "LambDynamicLights（动态光源）",
    "sodium-dynamic-lights": "Sodium Dynamic Lights（动态光源）",
    "camera-utils": "Camera Utils（相机工具）",
    "zoomify": "Zoomify（缩放）",
    "ok-zoomer": "Ok Zoomer（缩放）",
    "lighty": "Lighty（动态光照）",
    "presence-footsteps": "Presence Footsteps（脚步声）",
    "flywheel": "Flywheel（飞轮）",
    "rubidium": "Rubidium（铷·Forge 渲染）",
    "embeddium": "Embeddium（Forge 渲染）",
    "not-enough-animations": "Not Enough Animations（更多动画）",
    "3dskinlayers": "3D Skin Layers（3D 皮肤层）",
    "entitytexturefeatures": "Entity Texture Features（实体纹理特性）",
    "entity-model-features": "Entity Model Features（实体模型特性）",
    "sound-physics-remastered": "Sound Physics Remastered（物理声效重制）",
    "fancymenu": "FancyMenu（花哨菜单）",
    # ── 大型科技 / 魔法 ──
    "mekanism": "Mekanism（通用机械）",
    "ae2": "Applied Energistics 2（应用能源 AE2）",
    "thermal-expansion": "Thermal Expansion（热力膨胀）",
    "thermal-foundation": "Thermal Foundation（热力基础）",
    "draconic-evolution": "Draconic Evolution（龙之研究）",
    "botania": "Botania（植物魔法）",
    "biomes-o-plenty": "Biomes O' Plenty（超多生物群系）",
    "terralith": "Terralith（地形大修）",
    "waystones": "Waystones（路石）",
    "worldedit": "WorldEdit（创世神）",
    "chunky": "Chunky（区块预生成）",
    # ── 整合包（round-128 新增）──
    "fabulously-optimized": "Fabulously Optimized（FO·优化整合包）",
    "better-mc-fabric-bmc2": "Better MC（BMC2·Fabric 整合包）",
    "better-mc-forge-bmc4": "Better MC（BMC4·Forge 整合包）",
    "cobblemon-fabric": "Cobblemon（宝可梦整合包）",
    "prominence-2-fabric": "Prominence II（卓越 2 整合包）",
    "create-ultimate": "Create: Ultimate（机械动力：终极整合包）",
    "all-in-one": "All in One（综合整合包）",
    "vanilla-perfected": "Vanilla Perfected（原版完美化整合包）",
    "remarkably": "Remarkably Optimized（显著优化整合包）",
    "rso": "RSO（红石生电优化整合包）",
    "distant-horizons-iris-shaders": "Distant Horizons + Iris（远距离地平线光影整合包）",
    # ── 光影（round-128 新增）──
    "complementary-reimagined": "Complementary Reimagined（互补重制光影）",
    "complementary-unbound": "Complementary Unbound（互补无界光影）",
    "bsl-shaders": "BSL Shaders（BSL 光影）",
    "photon-shader": "Photon（光子光影）",
    "solas-shader": "Solas（索拉斯光影）",
    "bliss-shader": "Bliss（极乐光影）",
    "makeup-ultra-fast-shaders": "MakeUp Ultra Fast（极速光影）",
    "rethinking-voxels": "Rethinking Voxels（体素重思光影）",
    "super-duper-vanilla": "Super Duper Vanilla（超超原版光影）",
    "insanity-shader": "Insanity Shader（疯狂光影）",
    "sildurs-vibrant-shaders": "Sildur's Vibrant Shaders（Sildur 鲜艳光影）",
    "astralex": "Astralex（星界光影）",
    "nostalgia-shader": "Nostalgia（怀旧光影）",
    # ── 资源包（round-128 新增）──
    "faithful-32x": "Faithful 32x（忠实 32x）",
    "faithful-64x": "Faithful 64x（忠实 64x）",
    "fresh-animations": "Fresh Animations（生动动画）",
    "better-leaves": "Better Leaves（更好的树叶）",
    "bare-bones": "Bare Bones（极简材质）",
    "low-on-fire": "Low On Fire（低火焰）",
    "fast-better-grass": "Fast Better Grass（快速更好的草）",
    "dramatic-skys": "Dramatic Skys（戏剧天空）",
    "programmer-art-fix": "Programmer Art Fix（程序员艺术修复）",
}

# Modrinth 搜索不认中文，中文查询只能靠本地名库反查（round-128）。
_RE_CN_SPLIT = "（"


def cn_name(slug: str, fallback: str = "") -> str:
    """slug → 展示名（英文原名在前，中文翻译在后）；未收录返回 fallback。"""
    if not slug:
        return fallback
    return _MOD_CN.get(slug, fallback or slug)


def cn_short(slug: str) -> str:
    """「Sodium（钠·渲染优化）」→「钠」：取纯中文主体，用作 MC百科搜索词。

    只取「·」前的部分（「·」后是补充说明，搜索时反而添噪）。未收录返回 ""。
    """
    disp = _MOD_CN.get(slug or "", "")
    if not disp or _RE_CN_SPLIT not in disp:
        return ""
    body = disp.split(_RE_CN_SPLIT, 1)[1].rstrip("）)")
    return body.split("·", 1)[0].strip()


def cn_slug_map() -> dict:
    """中文主体 → [slug] 的反查表（供中文搜索使用）。"""
    out = {}
    for slug in _MOD_CN:
        short = cn_short(slug)
        if short:
            out.setdefault(short, []).append(slug)
    return out
