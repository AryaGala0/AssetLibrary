# AssetLibrary · 源码与数据存储说明

本文档面向**部署与二次开发**，重点说明代码结构、缩略图方案，以及**放到共享磁盘给多人使用**时各类数据的存放位置与权限要求。基础的调用方法见上一级目录的 `../README.md`。

## 代码结构

```
source/
├── assetLibrary_app.py     # 主窗口 + 偏好设置对话框（纯 Python 构建，DCC 无关）
├── dcc_interface.py        # DCC 适配层（打开/导入/引用/setProject/运行脚本/视口截图）
├── asset_lib_utils/        # 自带工具包（名字刻意避开通用的 utils）
│   ├── utils.py            # 通用工具 + AssetButton + 缩略图加载器/缓存/存储路径
│   ├── flowlayout.py       # FlowLayout 流式布局（跨 DCC 通用）
│   └── code_panel.py       # 代码界面（浏览 / 新建 / 编辑 / 运行 .py）
├── icon/                   # 图标资源
└── config/                 # 程序自带的默认配置（作为首次运行的"种子"，见下）
```

## 数据存储位置（共享盘多人使用的关键）

设计原则：**共享盘只放"只读、可共享"的数据；每个用户的私有数据和缓存都落到本机。** 这样即使程序和资产都在共享盘、普通用户只有只读权限，也不会产生写冲突或权限报错。

| 数据 | 位置 | 读写 | 说明 |
|------|------|------|------|
| 程序代码、图标 | 共享盘（程序目录） | 只读 | 所有人共用一份 |
| `config/*.json`（自带默认） | 共享盘（程序目录） | 只读 | 仅作首次运行的"种子"，运行期不写 |
| **偏好设置** `preference_config.json` | **本机用户配置目录** | 读写 | 每用户独立，互不覆盖 |
| **收藏** `favorite_config.json` | **本机用户配置目录** | 读写 | 每用户独立 |
| **已发布缩略图**（sidecar） | 共享盘 `<资产目录>/.thumbnails/<资产名>.png` | 读多写少 | 一人生成、所有人可见；写入需权限 |
| **本地兜底缩略图**（override） | **本机缓存目录** `overrides/` | 读写 | 共享盘只读时的个人兜底 |
| **缩略图解码缓存** | **本机缓存目录** `thumb_cache/` | 读写 | 缩放解码结果，纯加速，可随时删 |

### 本机目录按平台解析（`asset_lib_utils/utils.py`）

- **配置目录** `user_config_dir()`
  - Windows：`%APPDATA%\AssetLibrary`
  - macOS：`~/Library/Application Support/AssetLibrary`
  - Linux：`$XDG_CONFIG_HOME/AssetLibrary` 或 `~/.config/AssetLibrary`
- **缓存目录** `user_cache_dir()`
  - Windows：`%LOCALAPPDATA%\AssetLibrary\cache`
  - macOS：`~/Library/Caches/AssetLibrary`
  - Linux：`$XDG_CACHE_HOME/AssetLibrary` 或 `~/.cache/AssetLibrary`

首次运行时，若本机还没有 `preference_config.json` / `favorite_config.json`，会自动把程序自带 `config/` 下的同名文件拷过来作为初始值（`local_config_path()`），因此老用户的默认配置不会丢。

## 缩略图方案

### 生成（方案 C：视口截图）

资产卡片右键 `File Operation`：
- **Generate Thumbnail from Viewport**：把当前 DCC 视口截一帧作为该资产缩略图。
  - 优先**原子发布**到共享 sidecar（`publish_file_atomic`：同目录写临时文件再 `os.replace`，避免并发写坏、被别人读到半张图）；
  - 共享盘只读 / 无写权限时，**自动兜底**保存到本机 override，并提示"仅本人可见"，流程不中断。
- **Clear Thumbnail**：删除该资产缩略图（本机那份一定删；共享那份有权限才删）。

> 建议：由 TD / pipeline（对共享盘有写权限者）统一批量发布 sidecar 缩略图；普通美术只读即可看到，个别需要临时预览的自己生成，落到本机不影响他人。

也支持手动放置：直接把 `<资产名>.png` 放进资产目录的 `.thumbnails/` 子目录即可。资产本身是图片（png/jpg/…）时无需缩略图，直接用自己。

**显示源优先级**：资产本身是图片 → 共享 sidecar → 本机 override → 默认图标。

### 显示（高性能，应对大量资产）

`ThumbnailLoader`（`utils.py`）实现四层优化：

1. **解码即缩放**：`QImageReader.setScaledSize`，大图不整张读进内存；
2. **磁盘缓存**：解码结果按 `md5(源路径)_尺寸.jpg` 存本机 `thumb_cache/`，按 mtime 判新旧自动失效；
3. **异步加载**：`QThreadPool` 后台解码（子线程只产出 `QImage`，回主线程再转 `QPixmap`），界面秒开、缩略图渐进填充；
4. **可视区按需**：只给当前视口（含预取余量）内的卡片派发加载任务，滚动时动态补，资产总数再大也只解码可见的十几张。

缩略图缓存边长取偏好里的 `Thumbnail size`（默认 256）。

## 缓存清理

`thumb_cache/`、`overrides/` 都在本机缓存目录下，**目前不自动清理**，可安全手动删除（删后自动重建）。如需自动上限/LRU/孤儿清理，可在 `ThumbnailLoader` 扩展。

## 部署清单（共享盘场景）

1. 把整个程序目录放到共享盘，给普通用户**只读**权限即可。
2. 资产目录若希望共享缩略图，需要给"发布者"账号对 `.thumbnails/` 的**写**权限。
3. 普通用户无需任何写权限——偏好、收藏、缓存都会自动写到各自本机目录。
4. `sys.path` 指向共享盘的 `source/` 后照常 `import assetLibrary_app; assetLibrary_app.main()`。
