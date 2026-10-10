"""utils.py：通用工具 + AssetButton + AssetButtonGroup（DCC 无关）。

本文件不 import 任何 DCC 模块；文件操作统一走同级的 dcc_interface。
"""

import os
import time
import platform
import logging
import hashlib
from functools import partial

try:
    from PySide2 import QtWidgets, QtCore, QtGui
except ImportError:
    from PySide6 import QtWidgets, QtCore, QtGui

# 与本模板同级的 dcc 适配层；生成后路径为 source/dcc_interface.py
import dcc_interface


def open_folder_of_given_path(dir_path):
    """在系统文件管理器中打开目录（Windows 用 os.startfile）。"""
    if os.path.exists(dir_path):
        if platform.system() == "Windows":
            os.startfile(dir_path)
        else:
            import subprocess
            if platform.system() == "Darwin":
                subprocess.Popen(["open", dir_path])
            else:
                subprocess.Popen(["xdg-open", dir_path])


def resource_path(file_name):
    """解析相对 source 目录的资源绝对路径（程序自带的只读资源，如图标）。"""
    current_file_dir = os.path.dirname(__file__)
    return os.path.join(current_file_dir, "..", file_name)


APP_DIR_NAME = "AssetLibrary"


def user_config_dir():
    """每用户的本地配置目录（偏好、收藏等，可写、私有）。

    Windows: %APPDATA%\\AssetLibrary
    macOS:   ~/Library/Application Support/AssetLibrary
    Linux:   $XDG_CONFIG_HOME/AssetLibrary 或 ~/.config/AssetLibrary
    共享盘上程序为只读时，这些数据落到用户本机，多人互不干扰。
    """
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif system == "Darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config")
    path = os.path.join(base, APP_DIR_NAME)
    _ensure_dir(path)
    return path


def user_cache_dir():
    """每用户的本地缓存目录（缩略图解码缓存、本地兜底缩略图，可删不影响数据）。

    Windows: %LOCALAPPDATA%\\AssetLibrary\\cache
    macOS:   ~/Library/Caches/AssetLibrary
    Linux:   $XDG_CACHE_HOME/AssetLibrary 或 ~/.cache/AssetLibrary
    """
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") \
            or os.path.expanduser("~")
        path = os.path.join(base, APP_DIR_NAME, "cache")
    elif system == "Darwin":
        path = os.path.join(os.path.expanduser("~"), "Library", "Caches", APP_DIR_NAME)
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
            os.path.expanduser("~"), ".cache")
        path = os.path.join(base, APP_DIR_NAME)
    _ensure_dir(path)
    return path


def _ensure_dir(path):
    if path and not os.path.isdir(path):
        try:
            os.makedirs(path)
        except Exception:
            pass


def local_config_path(file_name):
    """返回本地配置文件路径；首次访问时若本地不存在而程序自带 config 里有，
    则把自带的那份拷过来做种子（保留原有默认收藏/偏好），之后一律读写本地。
    """
    local = os.path.join(user_config_dir(), file_name)
    if not os.path.exists(local):
        seed = resource_path(os.path.join("config", file_name))
        if os.path.exists(seed):
            try:
                import shutil
                shutil.copy2(seed, local)
            except Exception:
                pass
    return local


def find_files_in_path(path):
    """返回 path 下的所有文件路径（不含子目录）。"""
    if not os.path.isdir(path):
        return []
    return [os.path.join(path, n) for n in os.listdir(path)
            if not os.path.isdir(os.path.join(path, n))]


def find_dirs_in_path(path):
    """返回 path 下的所有子目录路径。"""
    if not os.path.isdir(path):
        return []
    return [os.path.join(path, n) for n in os.listdir(path)
            if os.path.isdir(os.path.join(path, n))]


def hum_convert(value):
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    size = 1024
    for unit in units:
        if value / size < 1:
            return f"{value}{unit}"
        value = round(value / size, 2)
    return f"{value}PB"


def delete_file(file_path):
    if os.path.exists(file_path):
        os.remove(file_path)


def rename_file(file_path, new_name):
    if os.path.exists(file_path):
        # 只按最后一个点取扩展名，忽略文件名中的其它点
        suffix = os.path.splitext(os.path.basename(file_path))[1]
        dir_name = os.path.dirname(file_path)
        new_path = os.path.join(dir_name, "{}{}".format(new_name, suffix))
        os.rename(file_path, new_path)


class MenuCustomStyle(QtWidgets.QProxyStyle):
    def __init__(self):
        super().__init__()

    def pixelMetric(self, metric, option, widget):
        if metric == QtWidgets.QStyle.PM_SmallIconSize:
            return 18
        return super().pixelMetric(metric, option, widget)


THUMB_DIR_NAME = ".thumbnails"
IMAGE_SUFFIXES = ("png", "jpg", "jpeg", "bmp", "tga", "tif", "tiff")


def sidecar_thumb_path(asset_path):
    """共享的 sidecar 缩略图路径：<资产目录>/.thumbnails/<资产全名>.png

    这是"已发布"的共享缩略图，随资产目录存放在共享盘上，所有人可读、一人生成大家受益。
    普通用户对共享盘通常只读，写入需有权限（TD / pipeline）。
    """
    if not asset_path:
        return ""
    directory = os.path.dirname(asset_path)
    base = os.path.basename(asset_path)
    return os.path.join(directory, THUMB_DIR_NAME, base + ".png")


def local_override_thumb_path(asset_path):
    """本地兜底缩略图路径：当共享盘只读、无法发布 sidecar 时，
    把用户自己生成的缩略图存到本机，按资产绝对路径 hash 命名，仅本人可见。
    """
    if not asset_path:
        return ""
    norm = os.path.normcase(os.path.abspath(asset_path))
    digest = hashlib.md5(norm.encode("utf-8")).hexdigest()
    directory = os.path.join(user_cache_dir(), "overrides")
    _ensure_dir(directory)
    return os.path.join(directory, digest + ".png")


def resolve_thumb_source(asset_path, asset_type):
    """返回该资产用于显示的原始图片路径；没有则返回空串。

    优先级：资产本身是图片 -> 共享 sidecar -> 本地兜底 override -> ""（用默认图标）。
    （解码后的缩放结果另有一层本地缓存，见 ThumbnailLoader。）
    """
    if not asset_path:
        return ""
    suffix = asset_path.rsplit(".", 1)[-1].lower() if "." in asset_path else ""
    if asset_type == "image" or suffix in IMAGE_SUFFIXES:
        return asset_path
    side = sidecar_thumb_path(asset_path)
    if os.path.exists(side):
        return side
    local = local_override_thumb_path(asset_path)
    if os.path.exists(local):
        return local
    return ""


def publish_file_atomic(src, dst):
    """把 src 原子性地发布到 dst（同目录写临时文件再 os.replace）。

    目标目录不可写（共享盘只读）时会抛异常，交由上层兜底。
    """
    dst_dir = os.path.dirname(dst)
    _ensure_dir(dst_dir)
    tmp = os.path.join(dst_dir, ".{}.tmp".format(os.path.basename(dst)))
    import shutil
    shutil.copy2(src, tmp)
    os.replace(tmp, dst)


class _ThumbTaskSignals(QtCore.QObject):
    done = QtCore.Signal(object, QtGui.QImage)


class _ThumbTask(QtCore.QRunnable):
    """后台线程里把图片解码成目标尺寸的 QImage（不碰 QPixmap，QPixmap 只能在主线程建）。

    方案 1：用 QImageReader.setScaledSize 解码即缩放，避免把整张大图读进内存。
    方案 2：结果写入磁盘缓存，下次直接读小图。
    """

    def __init__(self, key, src, cache_path, size, signals):
        super(_ThumbTask, self).__init__()
        self.key = key
        self.src = src
        self.cache_path = cache_path
        self.size = size
        self.signals = signals

    def run(self):
        image = QtGui.QImage()
        try:
            use_cache = (
                self.cache_path
                and os.path.exists(self.cache_path)
                and os.path.getmtime(self.cache_path) >= os.path.getmtime(self.src)
            )
            if use_cache:
                reader = QtGui.QImageReader(self.cache_path)
                image = reader.read()
            else:
                reader = QtGui.QImageReader(self.src)
                reader.setAutoTransform(True)
                src_size = reader.size()
                target = QtCore.QSize(self.size, self.size)
                if src_size.isValid() and not src_size.isEmpty():
                    scaled = src_size.scaled(target, QtCore.Qt.KeepAspectRatio)
                    if not scaled.isEmpty():
                        reader.setScaledSize(scaled)
                image = reader.read()
                if image is not None and not image.isNull() and self.cache_path:
                    try:
                        image.save(self.cache_path, "JPG", 85)
                    except Exception:
                        pass
        except Exception:
            image = QtGui.QImage()
        self.signals.done.emit(self.key, image if image is not None else QtGui.QImage())


class ThumbnailLoader(QtCore.QObject):
    """异步缩略图加载器（方案 3）：后台线程池解码，完成后用信号回主线程。

    - request(key, src)：为某张卡片请求缩略图，key 用于回调时找回对应卡片；
    - loaded(key, image)：加载完成信号；
    - invalidate(src)：删除某源图对应的磁盘缓存（重新生成缩略图后调用）。
    """

    loaded = QtCore.Signal(object, QtGui.QImage)

    def __init__(self, cache_dir, size=256, parent=None):
        super(ThumbnailLoader, self).__init__(parent)
        self.cache_dir = cache_dir
        self.size = max(32, int(size) if size else 256)
        self.pool = QtCore.QThreadPool.globalInstance()
        self._signals = _ThumbTaskSignals()
        self._signals.done.connect(self._on_done)
        self._pending = set()
        if cache_dir and not os.path.isdir(cache_dir):
            try:
                os.makedirs(cache_dir)
            except Exception:
                pass

    def cache_path_for(self, src):
        if not self.cache_dir or not src:
            return ""
        norm = os.path.normcase(os.path.abspath(src))
        digest = hashlib.md5(norm.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, "{}_{}.jpg".format(digest, self.size))

    def request(self, key, src):
        if not src or not os.path.exists(src):
            return
        if key in self._pending:
            return
        self._pending.add(key)
        task = _ThumbTask(key, src, self.cache_path_for(src), self.size, self._signals)
        self.pool.start(task)

    def _on_done(self, key, image):
        self._pending.discard(key)
        self.loaded.emit(key, image)

    def invalidate(self, src):
        cache_path = self.cache_path_for(src)
        if cache_path and os.path.exists(cache_path):
            try:
                os.remove(cache_path)
            except Exception:
                pass


class AssetButtonGroup(object):
    """维护一组资产卡片的单选互斥。"""
    def __init__(self):
        self.asset_buttons_list = None

    def add_button(self, button):
        if self.asset_buttons_list is None:
            self.asset_buttons_list = []
        self.asset_buttons_list.append(button)
        button.clicked.connect(partial(self.set_exclusive, button))

    def set_exclusive(self, clicked_button):
        for button in self.asset_buttons_list:
            button.setCheck(button == clicked_button)

    def set_selected(self, select):
        if select is None:
            if not self.asset_buttons_list:
                return
            for button in self.asset_buttons_list:
                button.setCheck(False)


class AssetButton(QtWidgets.QWidget):
    clicked = QtCore.Signal()
    double_clicked = QtCore.Signal()

    tag_qss_stylesheet = """
        font: 75 9pt "Arial";
        color: rgb(0,0,0);
        background-color: rgba(255,255,255,255);
        border: 2px solid rgba(255,255,255,255);
    """
    menu_qss_stylesheet = """
        QMenu { background-color: rgba(0,0,0); color: rgb(160,160,160); }
        QMenu::item { padding: 10px; }
        QMenu::item:selected { color: white; }
        QMenu::separator { height: 1px; background-color: rgb(55,55,55); }
    """
    suffix_label_color = {
        "3dObject": "rgba(136,195,227);",
        "image": "rgba(255,255,255,255);",
        "video": "rgba(254,212,98,255);",
        "texture": "rgba(150,140,239,255);",
        "executable": "rgba(255,140,100,255);",
    }

    def __init__(self, name, image_path, parent=None, is_folder=False):
        super(AssetButton, self).__init__(parent=parent)
        self.name = name
        self.image_path = image_path
        self.parent = parent
        self.asset_path = None
        self.asset_type = None
        self.is_folder = is_folder
        self.isChecked = False
        # 缩略图相关：thumb_source 为真正要显示的原图路径（由主窗口在 populate 时赋值），
        # thumb_key 供异步回调找回本卡片，_thumb_requested 防止重复请求，
        # _orig_pixmap 保存当前显示图的原始（未按滑块缩放的）pixmap，供 set_size 复用。
        self.thumb_source = ""
        self.thumb_key = None
        self._thumb_requested = False
        self._display_width = 60
        self._orig_pixmap = None
        self.set_custom_style()
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.create_menu)

    def set_custom_style(self):
        if self.is_folder:
            # 文件夹卡片：名字即目录名（无扩展名），标签固定显示 DIR
            name = self.name
            suffix = "DIR"
        else:
            try:
                # 只按最后一个点拆扩展名，文件名中的其它点保留在名字里
                name, suffix = self.name.rsplit(".", 1)
            except Exception:
                logging.error("the name of button should have a '.' extension")
                return
            suffix_type = self.get_suffix_categorized(suffix)
            if suffix_type:
                color = self.suffix_label_color[suffix_type]
                self.tag_qss_stylesheet = self.tag_qss_stylesheet.replace(
                    "rgba(255,255,255,255);", color)
            suffix = suffix.upper()
        self.setFixedWidth(120)
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setSpacing(0)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.tag_widget = QtWidgets.QFrame(self)
        tag_layout = QtWidgets.QHBoxLayout(self.tag_widget)
        tag_layout.setContentsMargins(0, 0, 0, 0)
        spacer = QtWidgets.QSpacerItem(0, 0, QtWidgets.QSizePolicy.Expanding,
                                       QtWidgets.QSizePolicy.Minimum)
        tag_label = QtWidgets.QLabel(suffix)
        tag_label.setStyleSheet(self.tag_qss_stylesheet)
        tag_layout.addItem(spacer)
        tag_layout.addWidget(tag_label)

        self.icon_label = QtWidgets.QLabel()
        # 只加载轻量的默认占位图标（object.png 等），真正的缩略图后台异步补上
        self._orig_pixmap = QtGui.QPixmap(self.image_path)
        self.pixmap = self._orig_pixmap
        self.icon_label.setPixmap(self.pixmap)

        self.asset_widget = QtWidgets.QWidget(self)
        asset_layout = QtWidgets.QHBoxLayout(self.asset_widget)
        asset_layout.setContentsMargins(0, 0, 0, 0)
        self.asset_name_label = QtWidgets.QLabel(name)
        self.asset_name_label.setWordWrap(True)
        self.asset_name_label.setAlignment(QtCore.Qt.AlignCenter)
        self.asset_name_label.setStyleSheet("background-color: rgba(255,255,255, 0);")
        asset_layout.addWidget(self.asset_name_label)

        self.main_layout.addWidget(self.tag_widget)
        self.main_layout.addWidget(self.icon_label)
        self.main_layout.addWidget(self.asset_widget)
        self.setStyleSheet("""
            border: 10px solid rgb(82, 133, 166, 0);
            background-color: rgba(255,255,255, 0);
        """)

    def get_suffix_categorized(self, suffix):
        object_format = ["ma", "mb", "obj", "abc", "usd"]
        image_format = ["png", "jpg"]
        video_format = ["avi", "mp4"]
        texture_format = ["spp"]
        executable_format = ["exe"]
        if suffix in object_format:
            self.asset_type = "3dObject"
        elif suffix in image_format:
            self.asset_type = "image"
        elif suffix in video_format:
            self.asset_type = "video"
        elif suffix in texture_format:
            self.asset_type = "texture"
        elif suffix in executable_format:
            self.asset_type = "executable"
        else:
            self.asset_type = None
        return self.asset_type

    def mousePressEvent(self, event):
        self.clicked.emit()

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()

    def open_in_dcc(self):
        """双击资产：文件夹进入该目录；exe 直接运行；其余在 DCC 中打开"""
        if not self.asset_path:
            return
        if self.is_folder:
            self.enter_folder()
        elif self.asset_type == "executable":
            self.run_exe()
        else:
            dcc_interface.open_file(self.asset_path)

    def enter_folder(self):
        """双击文件夹卡片：进入该目录（切换主窗口浏览路径）。"""
        enter = getattr(self.parent, "enter_directory", None)
        if enter is not None and self.asset_path:
            enter(self.asset_path)

    def run_exe(self):
        """运行 exe 文件"""
        if not self.asset_path or not os.path.exists(self.asset_path):
            return
        import subprocess
        import platform
        try:
            if platform.system() == "Windows":
                os.startfile(self.asset_path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", self.asset_path])
            else:
                subprocess.Popen([self.asset_path])
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, "Run", "Failed to run:\n{}".format(e))

    def generate_thumbnail(self):
        """方案 C：把当前 DCC 视口截图作为该资产的缩略图。

        优先原子发布到共享 sidecar（供所有人共享）；共享盘只读发布失败时，
        兜底保存到本机 override（仅本人可见），流程不中断。
        """
        if not self.asset_path:
            return
        # 先截图到本机临时文件（截图本身与最终落点解耦）
        tmp_path = os.path.join(user_cache_dir(), "_capture_tmp.png")
        try:
            saved = dcc_interface.capture_thumbnail(tmp_path, 256, 256)
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, "Thumbnail", "Failed to generate thumbnail:\n{}".format(e))
            return
        if not saved or not os.path.exists(saved):
            QtWidgets.QMessageBox.warning(
                self, "Thumbnail", "Failed to capture the viewport.")
            return

        shared = sidecar_thumb_path(self.asset_path)
        local = local_override_thumb_path(self.asset_path)
        published = False
        try:
            publish_file_atomic(saved, shared)
            published = True
        except Exception:
            # 共享盘只读或无写权限：退回本机 override
            try:
                publish_file_atomic(saved, local)
            except Exception as e:
                QtWidgets.QMessageBox.warning(
                    self, "Thumbnail", "Failed to save thumbnail:\n{}".format(e))
                self._cleanup_tmp(saved)
                return
        self._cleanup_tmp(saved)

        # 失效两处的解码缓存后刷新
        loader = getattr(self.parent, "thumb_loader", None)
        if loader is not None:
            loader.invalidate(shared)
            loader.invalidate(local)
        if not published:
            QtWidgets.QMessageBox.information(
                self, "Thumbnail",
                "No write permission to the shared library.\n"
                "The thumbnail was saved locally and is visible only to you.")
        self.parent.populate_asset_in_display_widget()

    def _cleanup_tmp(self, path):
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass

    def set_preview_image(self):
        """给文件夹（或资产）选一张图片作为预览：优先发布到共享 sidecar，
        失败则兜底到本机 override。"""
        if not self.asset_path:
            return
        img_filter = "Images (*.png *.jpg *.jpeg *.bmp *.tga *.tif *.tiff)"
        src, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose a preview image", "", img_filter)
        if not src:
            return
        shared = sidecar_thumb_path(self.asset_path)
        local = local_override_thumb_path(self.asset_path)
        published = False
        try:
            publish_file_atomic(src, shared)
            published = True
        except Exception:
            try:
                publish_file_atomic(src, local)
            except Exception as e:
                QtWidgets.QMessageBox.warning(
                    self, "Preview", "Failed to set preview image:\n{}".format(e))
                return
        loader = getattr(self.parent, "thumb_loader", None)
        if loader is not None:
            loader.invalidate(shared)
            loader.invalidate(local)
        if not published:
            QtWidgets.QMessageBox.information(
                self, "Preview",
                "No write permission to the shared library.\n"
                "The preview was saved locally and is visible only to you.")
        self.parent.populate_asset_in_display_widget()

    def clear_thumbnail(self):
        """删除该资产的缩略图（本地 override 一定删；共享 sidecar 有权限才删），恢复默认图标。"""
        shared = sidecar_thumb_path(self.asset_path)
        local = local_override_thumb_path(self.asset_path)
        for path in (local, shared):
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    # 共享盘只读时删不掉，忽略（本地那份已删）
                    pass
        loader = getattr(self.parent, "thumb_loader", None)
        if loader is not None:
            loader.invalidate(shared)
            loader.invalidate(local)
        self.parent.populate_asset_in_display_widget()

    def isCheck(self):
        return self.isChecked

    def setCheck(self, isCheck):
        self.isChecked = bool(isCheck)
        if self.isChecked:
            self.setStyleSheet("""
                background-color: rgba(0,0,0, 100);
                border: 10px solid rgba(82, 133, 166, 0);
            """)
        else:
            self.setStyleSheet("""
                background-color: rgba(0,0,0, 0);
                border: 10px solid rgba(82, 133, 166, 0);
            """)

    def set_path_to_clipboard(self):
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(os.path.dirname(self.asset_path))

    def set_file_to_clipboard(self):
        clipboard = QtWidgets.QApplication.clipboard()
        mime_data = QtCore.QMimeData()
        mime_data.setUrls([QtCore.QUrl.fromLocalFile(self.asset_path)])
        clipboard.setMimeData(mime_data)

    def delete_file(self):
        delete_file(self.asset_path)
        self.parent.populate_asset_in_display_widget()

    def rename_file(self):
        self.parent.get_input_dialog()
        new_name = self.parent.input_name
        rename_file(self.asset_path, new_name)
        self.parent.populate_asset_in_display_widget()

    def create_menu(self, pos=None):
        menu_style = MenuCustomStyle()
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(AssetButton.menu_qss_stylesheet)
        menu.setStyle(menu_style)

        if self.is_folder:
            menu.addAction("Open", self.enter_folder)
            menu.addAction("Open in Explorer",
                           partial(open_folder_of_given_path, self.asset_path))
            menu.addSeparator()
            menu.addAction("Set Preview Image", self.set_preview_image)
            # 用当前 DCC 视口拍屏作为文件夹封面
            if dcc_interface.can_capture_thumbnail():
                menu.addAction("Set Cover from Viewport", self.generate_thumbnail)
            if (os.path.exists(sidecar_thumb_path(self.asset_path))
                    or os.path.exists(local_override_thumb_path(self.asset_path))):
                menu.addAction("Clear Preview", self.clear_thumbnail)
            menu.exec_(QtGui.QCursor.pos())
            return

        sub_operation_menu = QtWidgets.QMenu()
        sub_operation_menu.setStyle(menu_style)
        sub_operation_menu.setTitle("File Operation")
        op_icon = resource_path("icon/file_operation.png")
        if os.path.exists(op_icon):
            sub_operation_menu.setIcon(QtGui.QIcon(op_icon))
        sub_operation_menu.addAction("Open", partial(dcc_interface.open_file, self.asset_path))
        sub_operation_menu.addAction("Import", partial(dcc_interface.import_file, self.asset_path))
        sub_operation_menu.addAction("Reference", partial(dcc_interface.reference_file, self.asset_path))
        if self.asset_type == "executable":
            sub_operation_menu.addSeparator()
            sub_operation_menu.addAction("Run", self.run_exe)
        sub_operation_menu.addSeparator()
        asset_path_dir = os.path.dirname(self.asset_path)
        sub_operation_menu.addAction("Open in Explorer",
                                     partial(open_folder_of_given_path, asset_path_dir))
        sub_operation_menu.addAction("Copy Path", self.set_path_to_clipboard)
        sub_operation_menu.addSeparator()
        sub_operation_menu.addAction("Copy", self.set_file_to_clipboard)
        sub_operation_menu.addAction("Delete", self.delete_file)
        sub_operation_menu.addAction("Rename", self.rename_file)
        sub_operation_menu.addSeparator()
        # 方案 C：从当前 DCC 视口生成缩略图；已有 sidecar 缩略图时可清除
        if dcc_interface.can_capture_thumbnail():
            sub_operation_menu.addAction(
                "Generate Thumbnail from Viewport", self.generate_thumbnail)
        if (os.path.exists(sidecar_thumb_path(self.asset_path))
                or os.path.exists(local_override_thumb_path(self.asset_path))):
            sub_operation_menu.addAction("Clear Thumbnail", self.clear_thumbnail)
        sub_operation_menu.addSeparator()
        sub_operation_menu.addAction("Add Tags")
        sub_operation_menu.setStyleSheet(AssetButton.menu_qss_stylesheet)
        menu.addMenu(sub_operation_menu)

        like_action = QtWidgets.QAction()
        like_icon = resource_path("icon/like.png")
        if os.path.exists(like_icon):
            like_action.setIcon(QtGui.QIcon(like_icon))
        menu.addAction(like_action)

        write_action = QtWidgets.QAction()
        write_icon = resource_path("icon/write.png")
        if os.path.exists(write_icon):
            write_action.setIcon(QtGui.QIcon(write_icon))
        menu.addAction(write_action)

        menu.exec_(QtGui.QCursor.pos())

    def get_information(self):
        self.asset_path = os.path.normpath(self.asset_path)
        create_time = time.ctime(os.path.getctime(self.asset_path))
        modify_time = time.ctime(os.path.getmtime(self.asset_path))
        if self.is_folder:
            # 文件夹：统计直接子项数量，而不是无意义的目录条目字节大小
            try:
                items = os.listdir(self.asset_path)
                file_count = sum(
                    1 for n in items
                    if os.path.isfile(os.path.join(self.asset_path, n)))
                dir_count = len(items) - file_count
                contents = "{} folders, {} files".format(dir_count, file_count)
            except Exception:
                contents = "N/A"
            return {
                "Name": self.name,
                "Type": "Folder",
                "Created": create_time,
                "Modified": modify_time,
                "Contents": contents,
                "Location": self.asset_path,
            }
        size = os.stat(self.asset_path).st_size
        return {
            "Name": self.name,
            "Type": self.asset_type,
            "Created": create_time,
            "Modified": modify_time,
            "Size": hum_convert(size),
            "Location": self.asset_path,
        }

    def set_size(self, width):
        # 始终从 _orig_pixmap 缩放，避免反复缩放导致越来越糊
        self._display_width = width
        if self._orig_pixmap and not self._orig_pixmap.isNull():
            self.pixmap = self._orig_pixmap.scaledToWidth(
                width, QtCore.Qt.SmoothTransformation)
            self.icon_label.setPixmap(self.pixmap)

    def set_thumbnail_image(self, image):
        """异步加载完成后回主线程调用：把 QImage 转成 pixmap 并按当前尺寸显示。"""
        if image is None or image.isNull():
            return
        pixmap = QtGui.QPixmap.fromImage(image)
        if pixmap.isNull():
            return
        self._orig_pixmap = pixmap
        self.set_size(self._display_width)
