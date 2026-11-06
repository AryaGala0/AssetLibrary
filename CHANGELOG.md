# 更新日志 (Changelog)

## 2026-11-02 Publish 增加发布后处理（Maya 打开 face_rig.ma 设属性 + 重排大纲 + 保存）

### 1. dcc_interface.py

- 新增发布后处理配置 `POST_PUBLISH_FACE_RIG_ATTRS`：`head_RL.dnaFilePath -> dna/head.dna`、`baseMapFile_head_color.fileTextureName -> Maps/color.jpg`、`baseMapFile_head_normal.fileTextureName -> Maps/normal.jpg`、`mapFile_head_wm1~wm3_normal.fileTextureName -> Maps/wm1~wm3.jpg`、`mapFile_head_cm1~cm3_color.fileTextureName -> Maps/cm1~cm3.jpg`（均为相对发布根目录的路径字符串）。
- 新增 `POST_PUBLISH_FACE_RIG_ROOT_GROUPS = {"root_bone": "Root", "meshes": ["head_lod0_grp"], "rig_type": "face"}`，对应 `lsr.maya.rig.utils.patch_rig_root_groups` 的入参。
- 新增 `_maya_setup_published_face_rig(path)`：`cmds.file(open=True, force=True)` 打开已发布文件 → 逐个 `cmds.setAttr(attr, value, type="string")`（属性不存在则跳过并记入返回值）→ `util.patch_rig_root_groups(**kwargs)` → `cmds.file(save=True, force=True)`。打开前若文件只读先补写权限，并把路径里的 `\` 换成 `/`。
- 新增对外接口 `can_setup_published_face_rig()`（只有 Maya 返回 True）与 `setup_published_face_rig(path)`（非 Maya 抛 `RuntimeError`，返回缺失属性列表）。
- 踩坑记录：`copy2` 会继承源文件的只读属性，共享盘资产发布会带着只读权限落到目标，`cmds.file(save=True)` 会直接报错，因此在打开前 `os.chmod` 补 `S_IWRITE`；Maya 命令对反斜杠敏感，Windows 路径统一转成正斜杠再传给 `cmds.file`。
- 踩坑记录：DCC 专属 import 必须留在本文件（其余模块不得 import DCC），所以 attrs 表与 patch 调用都放在 `dcc_interface.py`，`assetLibrary_app.py` 只调用两个对外函数。

### 2. assetLibrary_app.py

- 新增常量 `POST_PUBLISH_FACE_RIG = "scenes/rig/Referenced/face_rig.ma"`。
- `publish_asset_folder`：二次确认框里当本次任务包含该 face rig 且当前是 Maya 时追加提示——复制后会在 Maya 中打开该文件（当前场景会被替换）并设置属性/重排大纲后保存。
- 复制完成后调用新增的 `_post_publish_face_rig(dst_root)`，把结果并入发布结果弹窗：成功走 information，失败/非 Maya 环境走 warning，不阻断已完成的复制。
- 新增 `_post_publish_face_rig(dst_root)`：目标文件不存在则静默跳过；非 Maya 返回跳过提示；执行时 `setOverrideCursor(WaitCursor)` 防误操作；成功时汇报目标路径与被跳过的缺失属性。
- 踩坑记录：属性缺失（如资产只给了部分贴图节点）用跳过而非抛错，否则一个小资产缺节点就整条发布流程失败；缺失项集中汇报，避免"以为设上了"。

### 3. 补充：发布后处理前先切工程目录

- `dcc_interface.py`：`_maya_setup_published_face_rig(path, project_dir=None)` 在 `cmds.file(open=...)` 之前先 `cmds.workspace(project_dir, openWorkspace=True)`；`setup_published_face_rig(path, project_dir=None)` 透传该参数。
- `assetLibrary_app.py`：`_post_publish_face_rig(dst_root)` 调用时传入 `dst_root`，成功提示里带上工程目录；发布确认框的提示文案同步改为"先把工程切到发布目录，再打开 face rig"。
- 原因：属性值是 `dna/head.dna`、`Maps/color.jpg` 这类相对路径，必须落在发布的工程根目录下才有意义；先切 workspace 再打开场景，Maya 才不会按旧工程解析这些相对路径。
- 细节：workspace 与场景路径都先 `replace("\\", "/")`，避免 Windows 反斜杠被 Maya 当转义符。

## 2026-11-02 右键文件夹新增 Publish（选择发布路径 + 二次确认 + 按规则复制）

### 1. assetLibrary_app.py

- 新增模块级发布规则 `PUBLISH_RULES = (("dna", "dna"), ("fbx", "scenes/rig/Referenced/fbx"), ("scenes/rig.ma", "scenes/rig/Referenced/fbx/face_rig.ma"), ("SourceAssets", "Maps"))`：(源相对路径, 目标相对路径)，源是目录则递归复制其下所有文件到目标目录，源是文件则复制成目标文件（可顺便改名，如 `rig.ma -> face_rig.ma`）。
- 新增 `collect_publish_tasks(src_root, dst_root, rules=PUBLISH_RULES)` / `describe_publish_tasks(src_root)`：前者展开出 `(源文件, 目标文件)` 列表并返回缺失的源规则项，后者生成对话框用的预览行（目录附文件数、缺失打 `[missing]`）。
- 新增 `Publish_Dialog(QtWidgets.QDialog)`：源路径只读 + 目标路径 `QLineEdit` 与 `Browse...`（`QFileDialog.getExistingDirectory`）、规则预览 `QListWidget`、实时统计（总文件数 / 被跳过的缺失项）、OK 改名为 "Publish"；目标为空时 OK 置灰，`accept()` 里再兜底校验并把结果写到 `self.publish_path`。
- 新增主窗口入口 `publish_asset_folder(src_path=None)`：非目录直接提示；对话框确认后展开任务，任务为空提示"No rule matched"；随后用 `QMessageBox.question` 做二次确认（列出源/目标路径、文件数、覆盖提醒、逐条规则明细）；复制完弹结果（成功数、被跳过的缺失项、失败前 10 条），最后刷新资产显示区。
- 新增 `_copy_publish_tasks(tasks)`：`QProgressDialog` 逐个 `shutil.copy2`，先 `os.makedirs` 目标目录，可取消；失败不中断，收集错误信息后统一汇报。
- 主窗口 `__init__` 增加 `self.last_publish_path`，发布对话框默认带出上次选择的发布路径。
- `show_directory_menu` 中当右键项是目录时追加 `Publish` 项（文件不显示）。

### 2. asset_lib_utils/utils.py

- `AssetButton.create_menu` 的文件夹分支新增 `Publish` 菜单项，调用新增的 `AssetButton.publish_folder()`。
- 新增 `AssetButton.publish_folder()`：沿用 `enter_folder` 的回主窗口模式，通过 `getattr(self.parent, "publish_asset_folder", None)` 调用主窗口逻辑（`AssetButton` 仍不 import 主窗口、不碰 Qt 文件对话框）。

### 3. 踩坑记录

- 规则中 `dna -> dna`、`fbx -> scenes/rig/Referenced/fbx`、`SourceAssets -> Maps` 三类其实都是"目录 -> 目录"，只有 `scenes/rig.ma` 是"文件 -> 文件"：因此没有设计成 tree / file 两种模式，改为统一按 `os.path.isdir(src)` 判断——目录递归复制（保持子目录结构），文件直接复制。少一个参数、少一处分支出错点。
- 源目录中缺失的规则项（如没有 `dna`）不报错、不中断，只在预览与结果里列成 "Skipped (not found in source)"，避免一个资产不齐就发不了。
- 目标文件已存在时按"发布"语义直接覆盖（`shutil.copy2`），确认框里已明确提示，未做 `_unique_dest_path` 式的改名，否则反复发布会堆出一堆 `_copy`。

## 2026-10-28 Directory 路径栏右键菜单新增 "Open in Explorer"

### 1. assetLibrary_app.py

- `initUI` 中给顶部路径栏 `root_path_le` 设置 `Qt.CustomContextMenu`，并连接 `customContextMenuRequested` 到新增的 `show_root_path_menu`。
- 新增 `show_root_path_menu(pos)`：先用 `QLineEdit.createStandardContextMenu()` 拿到默认菜单（复制 / 全选等），再追加分隔线与 `Open in Explorer`，调用 `utils.open_folder_of_given_path(self.default_path)` 在系统文件管理器打开当前目录；当前路径无效时该项置灰。
- 踩坑记录：不要直接 `setContextMenuPolicy + 新建 QMenu` 整体替换默认菜单，否则只读路径栏原有的"复制/全选"会丢失；改为"标准菜单 + 追加自定义项"保留原功能。

## 2026-10-13 修复旧版 `reload(utils)` 引起的 "spec not found" 报错（AssetLibrary 旧目录）

### 1. AssetLibrary/source/assetLibrary_app.py（旧版本，非本工作区）

- 现象：在 Maya 里运行旧目录脚本报 `ModuleNotFoundError: spec not found for the module 'assetlib_utils'`，栈顶为 `assetLibrary_app.py` 的 `reload(utils)` 一行。
- 根因：`utils` 是用 `importlib.util.spec_from_file_location("assetlib_utils", ...)` 手动加载并写入 `sys.modules` 的模块，但名字 `assetlib_utils` 并不在 `sys.path` 上；`importlib.reload()` 会按模块名重新调用 `_find_spec` 去找 spec，找不到就抛出该错。且 `_load_local_module` 每次都会 `exec_module`，模块本就是全新的，这次 `reload` 纯属多余。
- 修复：去掉 `from imp import reload` 与 `reload(utils)`（随手清掉同样未使用的 `from pprint import pprint`），改为注释说明，防止以后又加回来。
- 勘误：2026-10-09 条目中“`reload(utils)` 仍可用”的说法不成立，特此更正——手动 spec 加载的模块无法被 `importlib.reload` 按名字重新定位。

## 2026-10-10 收藏栏支持“收藏文件夹”分类（新建 / 归类 / 拖拽）

按需求实现收藏栏的文件夹分组功能，约定：只支持一层（分类 → 文件夹 → 收藏项）、添加收藏时放进当前选中的文件夹、用拖拽把已有收藏归类。

### 1. assetLibrary_app.py

- 新增数据角色常量：`ROLE_PATH`（收藏项目录路径）、`ROLE_FOLDER`（文件夹名）、`ROLE_TYPE`（"category"/"folder"/"entry"）。
- 新增 `FavoriteTreeWidget`（收藏树控件）：`dragDropMode=InternalMove`，重写 `dropEvent` 校验——只允许拖动“收藏项”、且只能放到“文件夹/分类”节点上（`OnItem`），拒绝放到收藏项上/节点之间/外部文件拖入；拖拽成功后回调 `drop_handler`。
- 数据结构扩展：`favorites[category]` 变为节点列表，节点为收藏项 `{"path","name"}` 或文件夹 `{"folder","items":[...]}`（以 `"items"` 键区分，仅一层）。
- 新增方法：`normalize_favorite_node`、`is_favorite_folder`、`iter_favorite_entries`（含文件夹内）、`find_favorite_folder`、`locate_favorite_entry`（返回收藏项及其所在列表）、`_build_favorite_entry_item`、`current_selected_folder`、`add_favorite_folder`、`on_favorite_tree_dropped`（按树结构重建数据并保存）。
- `load_favorites` 改用 `normalize_favorite_node`，兼容旧的收藏项列表配置（旧数据无需迁移）。
- `populate_favorite_tree` 重建三层树：分类（不可编辑/不可拖、可作拖放目标）→ 文件夹（可编辑、可作拖放目标、不可拖）→ 收藏项（可编辑、可拖、不可作目标）；文件夹用 `icon/folder.png` 显示。
- `add_favorite`：选中的是文件夹则放进该文件夹，否则放分类根目录。
- `remove_favorite_item`/`rename_favorite_item`/`on_favorite_item_changed`：区分文件夹与收藏项，文件夹改名做重名校验，收藏项改名/恢复名沿用原逻辑。
- `open_favorite_item`：单击文件夹展开；单击分类切界面；单击收藏项打开目录（保持原行为）。
- `show_favorite_menu`：右键先选中该节点；新增 `New Folder`；文件夹只给 `Rename`/`Remove`，收藏项给 `Open`/`Open in Explorer`/`Rename`/`Reset Name`/`Remove`。
- 踩坑记录：拖拽用 `InternalMove` 后 Qt 会自动移动节点，因此不在 `dropEvent` 里手改数据，而是 `dropEvent` 后按“树的新结构”重建 `favorites`（从各节点的 `ROLE_TYPE`/`ROLE_PATH` 还原），避免自维护与 Qt 视图状态不一致；删除收藏项时因其可能在分类根或某文件夹内，用 `locate_favorite_entry` 拿到所在列表再删，避免直接 `list.remove` 删不到文件夹内的项。

## 2026-10-09 修复旧版 `utils` 包名冲突报错（AssetLibrary 旧目录）

### 1. AssetLibrary/source/assetLibrary_app.py（旧版本，非本工作区）

- 现象：在 Maya 里运行旧目录脚本报 `ModuleNotFoundError: No module named 'utils.utils'; 'utils' is not a package`。
- 根因：旧代码把工具模块放在 `source/utils/` 且该目录没有 `__init__.py`，而 Maya/rez 环境（lsr_python_core 的 import 钩子）里已存在一个名为 `utils` 的模块，`import utils.utils` 时 `utils` 被解析成该非包模块，导致失败（命名冲突）。
- 修复：把文件开头的 `import utils.utils as utils` / `import utils.flowlayout as flow_layout` 改为用 `importlib.util.spec_from_file_location` 按文件路径加载，并赋予唯一模块名 `assetlib_utils` / `assetlib_flowlayout`，彻底避开 `utils` 命名冲突；变量名仍沿用 `utils` / `flow_layout`，其余引用无需改动，`reload(utils)` 仍可用。
- 说明：本工作区的新版 `AssetLibrary2` 已用 `asset_lib_utils` 包名从结构上规避了该问题，故不涉及此修复。

## 2026-10-08 文件夹卡片：点击看属性 + 右键设封面（选图/拍屏）

### 1. asset_lib_utils/utils.py

- `AssetButton` 增加 `is_folder` 模式：`set_custom_style` 对文件夹跳过扩展名解析、标签显示 `DIR`；`open_in_dcc` 对文件夹改为 `enter_folder()`（调主窗口 `enter_directory` 进入该目录）。
- `get_information()` 适配文件夹：Type 显示 `Folder`，用 `Contents`（统计直接子项"N folders, M files"）替代无意义的目录字节大小；点击文件夹卡片即可在信息栏看到这些属性。
- 文件夹右键菜单：`Open` / `Open in Explorer` / `Set Preview Image`（选本地图片）/ **`Set Cover from Viewport`（当前 DCC 视口拍屏设为封面，复用 `generate_thumbnail`）** / `Clear Preview`。
- 新增 `set_preview_image()`：选图后优先原子发布到共享 sidecar，只读则兜底本机 override。封面沿用 `sidecar_thumb_path`/`local_override_thumb_path`，与资产缩略图同一套异步加载/缓存体系。

### 2. assetLibrary_app.py

- `populate_asset_in_display_widget`：当前目录无任何资产时调用 `_populate_folder_cards()` 把子文件夹显示为卡片（跳过以 `.` 开头的隐藏目录），支持预览图异步加载、双击进入、点击显示属性。
- 新增 `enter_directory(path)`：文件夹卡片双击时切换浏览路径。

### 3. assetLibrary_app.py（资产区空白处右键新增文件夹）

- 资产显示区空白处右键菜单 `show_asset_area_menu` 最上方新增 `New Folder` 项，位于 `Set Project` 之前，与粘贴/工程设置分组用分隔线隔开。
- 新增 `create_new_folder()`：以 `self.default_path`（当前打开目录）为目标，弹输入框输入名称，校验当前目录有效、名字非空、目标不重名后 `os.makedirs` 建目录；失败给出警告，成功后 `populate_tree_view_ui()` 刷新目录树与资产区（新建的空文件夹会以文件夹卡片显示）。

## 2026-09-30 修复：文件识别改为只按最后一个点取扩展名（支持路径/文件名含点）

- 现象：父目录名或文件名里带点（如 `monsterInc.Sullivan`）时，该目录下资产全部不显示。根因：旧逻辑用 `完整路径.split(".")` 数点、要求恰好 2 段，父路径有点就被判为非资产。
- 修复（改识别方式，只认最后一个点为扩展名分隔，其它点忽略）：
  - `assetLibrary_app.py` `get_all_directory_files` / `get_files_in_specific_directory`：改用 `os.path.splitext(os.path.basename(...))[1]` 判断是否有扩展名。
  - `assetLibrary_app.py` `populate_asset_in_display_widget`：`name.split(".")` 改为 `name.rsplit(".", 1)`，多点文件名（如 `sullivan.v001.ma`）不再报错、名字里的点保留。
  - `asset_lib_utils/utils.py` `rename_file`：改用 `os.path.splitext` 取扩展名（含点），拼名改为 `新名+扩展名`。
  - `asset_lib_utils/utils.py` `AssetButton.set_custom_style`：`self.name.split(".")` 改为 `rsplit(".", 1)`。

## 2026-09-30 共享盘多人使用改造：配置/缓存本地化 + 缩略图两层存储 + README

面向"资产库放共享磁盘、普通用户只读"的场景，把私有数据和缓存挪到各用户本机，缩略图改为"共享只读 + 本地兜底"两层。

### 1. asset_lib_utils/utils.py

- 新增 `user_config_dir()` / `user_cache_dir()`：按平台解析每用户本地配置/缓存目录（Win 用 APPDATA/LOCALAPPDATA，mac 用 Library，Linux 用 XDG）；`_ensure_dir()` 助手。
- 新增 `local_config_path(file_name)`：返回本地配置路径，首次访问时若本地没有而程序自带 `config/` 里有，则拷贝作为种子（保留老用户默认收藏/偏好）。
- 缩略图存储改两层：`sidecar_thumb_path()` 定位为共享只读的"已发布"缩略图；新增 `local_override_thumb_path()`（本机 `cache/overrides/<md5>.png`）作为共享盘只读时的个人兜底；`resolve_thumb_source()` 查找顺序改为「资产自身图片 → 共享 sidecar → 本地 override → 空」。
- 新增 `publish_file_atomic(src, dst)`：同目录写临时文件再 `os.replace` 原子发布，避免并发写坏/读到半张图；共享盘不可写时抛异常交上层兜底。
- `AssetButton.generate_thumbnail()` 重写：先截图到本机临时文件，优先原子发布到共享 sidecar，失败（只读/无权限）则兜底写本机 override 并提示"仅本人可见"，全程不中断；新增 `_cleanup_tmp()`。`clear_thumbnail()` 改为本地 override 必删、共享 sidecar 有权限才删。右键 `Clear Thumbnail` 的显示条件同时考虑两处。

### 2. assetLibrary_app.py

- 偏好读写、收藏读写全部改用 `utils.local_config_path(...)`（本机用户目录）：`load_preference_config`、`load_favorites`、`save_favorites`、`Preference_Dialog.config_file_path`（由类属性改为 `__init__` 内按本地路径计算）。
- 缩略图解码缓存目录从 `config/thumb_cache`（共享）改为 `user_cache_dir()/thumb_cache`（本机），避免多人写冲突。

### 3. 文档

- 新增 `source/README.md`：代码结构、缩略图方案、**共享盘多人使用的数据存储位置与权限表**、部署清单。
- 根 `README.md` 目录结构补充 config 定位说明，并加指引指向 `source/README.md`。

## 2026-09-30 资产缩略图：视口生成（方案C）+ 高性能异步加载（方案1+2+3+4）

### 1. asset_lib_utils/utils.py

- 新增 `sidecar_thumb_path()` / `resolve_thumb_source()`：缩略图以 sidecar 形式存放在 `<资产目录>/.thumbnails/<资产全名>.png`；显示源图优先级为「资产本身是图片 → sidecar → 无（用默认图标）」。
- 新增 `ThumbnailLoader`(+`_ThumbTask`/`_ThumbTaskSignals`)：
  - 方案1 用 `QImageReader.setScaledSize` 解码即缩放，避免把大图整张读进内存；
  - 方案2 结果按 `md5(源路径)_尺寸.jpg` 存入磁盘缓存（`config/thumb_cache/`），并按 mtime 判新旧，源图更新自动失效；
  - 方案3 用 `QThreadPool` 后台解码，子线程只产出 `QImage`（QPixmap 只能主线程建），完成经 `loaded` 信号回主线程；
  - `invalidate()` 供重建缩略图后清缓存。
- `AssetButton` 改造：`__init__` 只加载轻量占位图标不再同步解码大图；新增 `thumb_source/thumb_key/_thumb_requested/_orig_pixmap`；`set_size` 改为始终从 `_orig_pixmap` 平滑缩放（修复反复缩放变糊）；新增 `set_thumbnail_image()`（异步回主线程后转 pixmap 显示）。
- 右键 File Operation 菜单：支持视口生成时显示 `Generate Thumbnail from Viewport`，已有 sidecar 时显示 `Clear Thumbnail`；新增 `generate_thumbnail()`（调 `dcc_interface.capture_thumbnail` 写 sidecar 并刷新）/ `clear_thumbnail()`。

### 2. dcc_interface.py

- 新增 `capture_thumbnail(out_path, width, height)` 及 `can_capture_thumbnail()`（方案C）：Maya 用 `cmds.playblast` 单帧、Max 用 `gw.getViewportDib`、Blender 用 `render.opengl(write_still=True)`（临时改分辨率后还原），standalone 不支持抛错。公共函数对 DCC 自动追加扩展名的情况做兜底查找。新增 `_CAPTURE_THUMBNAIL` 分发表；补 `import os`。

### 3. assetLibrary_app.py

- `initUI` 读偏好 `Thumbnail size`（默认 256）创建 `utils.ThumbnailLoader`（缓存目录 `config/thumb_cache`），连 `loaded -> _on_thumbnail_loaded`。
- `_build_middle_widget` 保存 `asset_scroll_area` 引用，监听竖直滚动条 `valueChanged`/`rangeChanged` 触发按需加载（方案4）。
- `populate_asset_in_display_widget` 为每张卡片解析 `thumb_source` 并登记 `key->卡片` 映射（每次重建清空，令旧的异步回调自然失效），布局稳定后 `QTimer.singleShot(0)` 触发可视区加载。
- 新增 `_update_visible_thumbnails()`（仅对视口内含预取余量的卡片派发请求，去重）/ `_on_thumbnail_loaded()`（找回卡片设图，卡片已销毁则忽略 RuntimeError）。

## 2026-09-28 新增 exe 资产显示与右键 Run

### asset_lib_utils/utils.py

- `suffix_label_color` 新增 `"executable": "rgba(255,140,100,255);"` —— exe 卡片标签显示橙色。
- `get_suffix_categorized()` 新增 `executable_format = ["exe"]` 分支，`asset_type` 返回 `"executable"`，使 exe 文件能通过过滤显示在资产区。
- 新增 `run_exe()`：Windows 用 `os.startfile`，macOS 用 `open`，Linux 直接 `Popen`。
- `create_menu()` 在 Import / Reference 之后针对 `asset_type == "executable"` 插入分隔线 + `Run` 菜单项，调用 `run_exe()`。

## 2026-09-28 .py 文件右键新增 Run in DCC

### 1. dcc_interface.py

- 新增对外函数 `run_script(path)`，在当前 DCC 中运行 .py 脚本，standalone 下用 `_exec_py_in_main` 兜底。
- 新增通用辅助 `_exec_py_in_main(path)`：读取文件在 `__main__` 命名空间 `exec`，并把 `__file__` 设为脚本路径；Maya / Blender 均复用它（等同脚本编辑器里运行）。Max 用 `rt.python.ExecuteFile(path)`。
- 新增 `_maya_run_script` / `_max_run_script` / `_blender_run_script` 及 `_RUN_SCRIPT` 分发表。

### 2. asset_lib_utils/code_panel.py

- 代码文件右键菜单在选中文件时最上方新增 `Run in DCC`（其后加分隔线）。
- 新增 `run_in_dcc()`：对选中的 .py 调用 `dcc_interface.run_script`（方法内局部 import，保持模块顶部不依赖 DCC），失败弹警告。

## 2026-09-28 中间资产区空白右键新增 Paste（系统剪贴板文件）

### assetLibrary_app.py

- `show_asset_area_menu()` 在 Set Project 下方加 `Paste` 项，剪贴板无文件时置灰。
- 新增 `get_clipboard_file_paths()`：读取系统剪贴板 mimeData 的本地文件 URL（过滤不存在的路径），返回路径列表。
- 新增 `paste_from_clipboard()`：把剪贴板里的文件（夹）逐个复制到当前目录 `self.default_path`，用 `_unique_dest_path` 避免同名覆盖，`shutil.copytree`/`copy2` 复制，完成后刷新目录树；部分失败会汇总提示。既支持应用内 Copy 的文件，也支持从资源管理器复制的文件。

## 2026-09-28 双击资产在 DCC 中打开

### 1. asset_lib_utils/utils.py

- `AssetButton` 新增 `double_clicked` 信号与 `mouseDoubleClickEvent`（发射该信号）。
- 新增 `open_in_dcc()`：调用 `dcc_interface.open_file(self.asset_path)` 在 DCC 中打开资产。

### 2. assetLibrary_app.py

- `populate_asset_in_display_widget()` 里为每个资产卡片连接 `double_clicked -> file_btn.open_in_dcc`，双击资产即在 DCC 中打开（与右键菜单的 `Open` 行为一致）。

## 2026-09-28 中间资产显示区右键新增 Set Project

### 1. dcc_interface.py

- 新增对外函数 `set_project(path)` 及各 DCC 实现：Maya `cmds.workspace(path, openWorkspace=True)`、Max `rt.pathConfig.setCurrentProjectFolder(path)`、Blender no-op（无工程目录概念）。新增 `_SET_PROJECT` 分发表，沿用现有分发模式。

### 2. assetLibrary_app.py

- 给中间资产显示区 `outside_diaplay_widget` 设 `CustomContextMenu`，空白处右键弹出菜单（`AssetButton` 自身有右键菜单，点在资产卡片上不受影响，只有点空白处才走此菜单）。
- 新增 `show_asset_area_menu()` / `set_project_to_current_dir()`：右键 `Set Project` 把当前目录 `self.default_path` 设为 DCC 工程目录；目录无效或调用失败时弹警告，成功后在状态栏 `asset_status_le` 显示 `Project: <路径>`。

## 2026-09-28 资产目录树右键菜单新增 Rename

### 1. assetLibrary_app.py

- `show_directory_menu()`：在右键 index 有效时，菜单顶部加入 `Rename` 项，排在 `Copy` 前面。
- 新增 `rename_directory_item(path)`：弹 `QInputDialog.getText`，预填当前名称；确认后检查目标路径是否已存在，不存在则 `os.rename`，完成后刷新目录树；名字为空、未修改、取消均不执行。

## 2026-09-28 收藏项单击导航 + 修复点击空白区报错

### 1. assetLibrary_app.py

- 新增 `itemClicked` 连接到 `open_favorite_item`：单击收藏项即可跳到对应资产/代码目录，无需双击。双击仍保留就地改名行为，两者不冲突（单击触发导航，双击触发编辑）。

### 2. asset_lib_utils/utils.py

- 修复 `AssetButtonGroup.set_selected(None)` 在 `asset_buttons_list` 为 `None` 时抛出 `TypeError: 'NoneType' object is not iterable` 的问题。根因：资产面板为空（无任何资产卡片）时 `add_button` 从未被调用，`asset_buttons_list` 仍是初始值 `None`；点击面板空白处触发 `set_selected(None)` 就崩溃。修复：在遍历前加 `if not self.asset_buttons_list: return`。

## 2026-09-28 收藏项双击就地改名 + 资产目录树复制粘贴

### 1. assetLibrary_app.py

- 收藏项支持双击就地重命名：`favorite_tree_widget.itemDoubleClicked` 由原来的 `open_favorite_item` 改接 `on_favorite_double_clicked`——双击具体收藏项进入就地编辑（`editItem`）直接改标签名，双击分类名（Asset/Code）仍切换到对应界面。打开收藏项的功能保留在右键菜单 `Open`。
- 新增 `on_favorite_double_clicked()` / `on_favorite_item_changed()`：编辑完成经 `itemChanged` 把新名字写回 `config/favorite_config.json`；空名字自动恢复原名。
- `populate_favorite_tree()`：收藏项加 `ItemIsEditable` 标志、分类项去掉该标志；重建期间用 `self._favorite_loading` 屏蔽 `itemChanged`，避免重建误触发改名。
- 资产目录树（`directory_treeview`）新增右键菜单支持复制/粘贴文件（夹）：新增 `show_directory_menu()` / `copy_directory_item()` / `paste_directory_item()` / `_unique_dest_path()`。
  - Copy 记入内部剪贴板 `self._dir_clipboard_path`，同时写入系统剪贴板 URL（方便到资源管理器直接粘贴）。
  - Paste 目标目录判定：右键目录则粘进去、右键文件则粘到其所在目录、空白处则粘到当前根目录；用 `shutil.copytree`/`copy2` 复制，同名时自动追加 `_copy`/`_copy2...` 避免覆盖，完成后刷新目录树。
  - 剪贴板为空时 `Paste` 菜单置灰。



- 收藏数据结构从"路径字符串数组"改为 `{"path": 路径, "name": 显示名}`；新增 `normalize_favorite_entry()` 兼容旧配置（字符串条目自动用目录名当显示名），`find_favorite_entry()` 按路径查条目。
- 新增 `rename_favorite_item()`：收藏项右键 -> `Rename`，弹输入框改**显示名**（只改标签，不动磁盘上的目录），立即写回 `config/favorite_config.json`，重启后仍在。
- 新增 `reset_favorite_name()`：右键 -> `Reset Name`，把显示名恢复成目录名。
- 选中收藏项后按 `F2` 可直接改名（`QShortcut`，`WidgetShortcut`，只在收藏树聚焦时生效）。
- 右键菜单顺序：`Open` / `Open in Explorer` / `Rename` / `Reset Name` / `Remove` / `Refresh`。
- `add_favorite()` 的重复判断、`remove_favorite_item()`、`switch_to_category_view()` 的 Code 兜底都改为按新结构取 `entry["path"]`。

## 2026-09-28 资产查询层级改为 1 层

- 新增常量 `ASSET_QUERY_LEVEL = 1`（1 = 只查当前打开的目录，2 = 再往下查一层子目录）。
- `self.asset_depth["level_nums"]` 由写死的 `1` 改为 `ASSET_QUERY_LEVEL - 1`（`level_nums` 是"再往下钻几层"，查询 1 层对应 0）。
- 效果：打开一个目录后右侧只列出该目录里的资产，不再去每个子目录里找文件。想恢复原来的行为把 `ASSET_QUERY_LEVEL` 改成 2 即可。

## 2026-09-21 工具包 utils 改名为 asset_lib_utils（修复 Maya 导入失败）

- Maya 里 `import assetLibrary_app` 报 `No module named 'utils.utils'; 'utils' is not a package`：环境（rez / LSR 等）里已有一个名为 `utils` 的普通模块，我们的 `utils/` 目录没有 `__init__.py`、只是"命名空间包"，优先级低于任何真实的 `utils` 模块，于是被抢先匹配。
- 把 `source/utils/` 整个包改名为 `source/asset_lib_utils/`（并补了 `__init__.py`），彻底避开同名冲突，不依赖 `sys.path` 顺序。
- 同步更新：`assetLibrary_app.py` 的三条 import、`asset_lib_utils/code_panel.py` 内的 `import asset_lib_utils.utils as utils`、README 目录结构。
- 旧 `utils/` 目录及其 `__pycache__` 已删除。

## 2026-09-21 左下角增加 Asset / Code 收藏分类

### 1. assetLibrary_app.py

- 左下角 tag 面板改为收藏面板：头部加 "Favorite" 标签，`tag_treeview`（空 `QTreeView`）替换为 `favorite_tree_widget`（`QTreeWidget`），固定两个顶层分类 `Asset` / `Code`。
- 新增 `ASSET_CATEGORY` / `CODE_CATEGORY` 常量与 `self.favorites = {"Asset": [], "Code": []}`。
- 新增方法：`load_favorites()` / `save_favorites()` / `populate_favorite_tree()` / `get_favorite_category_of_item()` / `current_favorite_category()` / `add_favorite()` / `remove_favorite_item()` / `open_favorite_item()` / `show_favorite_menu()`。
- 收藏入口有两个：左下角 `+` 号（按选中分类或当前界面自动判断收 Asset 还是 Code）、代码界面右键菜单 `Add to Favorites`（固定收 Code）。
- 双击收藏项：Code 项切到代码界面并加载该目录（同时更新 `self.code_path`），Asset 项切回资产界面并 `populate_tree_view_ui()` 跳到该目录。
- 修复：双击 Code 收藏时会先 `switch_code_view(True)`，此时新目录还没设上，`switch_code_view` 判断"代码目录无效"于是弹出 `QFileDialog` 选择目录窗口；改为先 `set_code_path(path)` + 设 `self.code_path` 再切界面，双击即直达代码界面。
- 双击分类名本身（`Asset` / `Code` 顶层项）现在也会切到对应界面：新增 `switch_to_category_view()`，Asset 回到资产界面并刷新目录树，Code 切到代码界面（代码目录未设时用该分类第一条可用收藏兜底，不弹选择目录窗口）。之前顶层项被 `item.parent() is None` 直接 return，双击没反应。
- 右键菜单：`Add <分类> Directory` / `Open` / `Open in Explorer` / `Remove` / `Refresh`。

### 2. utils/code_panel.py

- 右键菜单新增 `Add to Favorites`，新增 `add_code_dir_to_favorites()`，通过 `main_win.add_favorite("Code")` 复用主窗口逻辑（不直接依赖 app 模块，避免循环 import）。
- 修复：右键列表不会改变 `currentItem`，导致 Open / Rename / Delete / Copy 作用在"上一个选中项"上；现在 `show_menu()` 会先 `setCurrentItem(item)`。

### 3. config/favorite_config.json（新建）

- 收藏持久化文件，结构 `{"Asset": [路径...], "Code": [路径...]}`，增删收藏时立即写回。

### 踩坑记录

- 冒烟测试中先 `switch_code_view(True)` 再设代码目录会触发 `choose_code_path()` 的模态 `QFileDialog`，offscreen 下永久阻塞；测试顺序必须先 `set_code_path()` 再切换界面。
- `QMessageBox.information/warning` 是静态方法，会直接 exec 模态循环，测试中触发会卡死/崩溃；同理断言用例要避开"已收藏"等提示分支。
- 测试脚本会真实读写 `config/favorite_config.json`，必须先备份再在结尾还原，否则会污染本机收藏数据（本次已清理并恢复原有 `E:/Personal/code/work` 一条收藏）。

## 2026-09-16 新增代码界面与代码路径设置

### 1. utils/code_panel.py（新建）

- 新增 `CodePanelWidget`：代码文件面板，列出代码目录下所有 `.py`（递归扫描，跳过 `__pycache__`），带路径栏、浏览/刷新/新建/删除按钮。
- 右键菜单支持：New Python File / Paste / Open / Rename / Duplicate / Delete / Copy / Copy Path / Open in Explorer / Refresh（无选中项时只显示新建、粘贴、刷新）。
- 新增 `CodeEditorDialog`：`QPlainTextEdit` 编辑窗口，可改名后保存即完成重命名，支持 Save / Save As / Reload / Close、`Ctrl+S`、复制粘贴、关闭前询问保存。
- 新增 `PythonHighlighter`（用 python `re` 实现，规避 PySide2/6 正则 API 差异）与 `exec_dialog()`（兼容 `exec_` / `exec`）。

### 2. assetLibrary_app.py

- 搜索栏左侧新增 `code_view_btn`（`write.png` 图标，可勾选），点击通过 `view_stack`（`QStackedWidget`）在资产界面与代码界面间切换，代码界面下隐藏信息栏、搜索栏转为过滤 py 文件。
- 新增 `switch_code_view()` / `filter_display()`；`add_asset()` 在代码界面下改为新建 py 文件。
- 偏好设置新增 "Code Root Path" 分组（输入框 + `root_path.png` 浏览按钮），保存键 `code path` 写入 `config/preference_config.json`；保存后立即同步到主窗口代码面板。
- 新增 `load_preference_config()`，启动时读取 `default path` 与 `code path`；`code path` 为空时回退到 `<资产根目录>/code`。
- `init_preference_info()` 改为容错读取（`.get`）并回填语言、默认路径、代码路径；`save_preference_info()` 改用 `with open` 写文件。

### 3. config/preference_config.json

- 新增 `"code path": ""` 字段并格式化为缩进 JSON。

### 踩坑记录

- 本地环境无 PySide2/PySide6，无法直接跑 UI；改用 Maya2024 自带 `mayapy.exe`（PySide2 5.15.2.1 + Python 3.10）配合 `QT_QPA_PLATFORM=offscreen` 完成冒烟测试（界面切换、编辑写入、改名、过滤、偏好保存），测试脚本已删除。
- 冒烟测试中通过 `__new__` 构造 `Preference_Dialog` 会触发 `RuntimeError: '__init__' method of object's base class not called`（`QDialog(self)` 需要已初始化的 self），改为临时替换 `QDialog.exec_` 屏蔽模态循环后正常构造。
- `QPlainTextEdit.setTabStopWidth` 在 PySide6 已移除，代码用 `try/except` 回退到 `setTabStopDistance`。
