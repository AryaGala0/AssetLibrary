import os
import shutil
import json
import importlib
from functools import partial

try:
    from PySide2 import QtWidgets, QtCore, QtGui
except ImportError:
    from PySide6 import QtWidgets, QtCore, QtGui

import dcc_interface
import asset_lib_utils.utils as utils
import asset_lib_utils.flowlayout as flow_layout
import asset_lib_utils.code_panel as code_panel


# 左下角收藏面板的两个分类
ASSET_CATEGORY = "Asset"
CODE_CATEGORY = "Code"

# 资产查询层级：1 = 只查当前打开的目录，2 = 再往下查一层子目录，以此类推
ASSET_QUERY_LEVEL = 1

# 收藏树里挂在 QTreeWidgetItem 上的数据角色
ROLE_PATH = QtCore.Qt.UserRole          # 收藏项对应的目录路径
ROLE_FOLDER = QtCore.Qt.UserRole + 1    # 收藏文件夹的名字（用于定位文件夹节点）
ROLE_TYPE = QtCore.Qt.UserRole + 2      # 节点类型："category" / "folder" / "entry"


class FavoriteTreeWidget(QtWidgets.QTreeWidget):
    """收藏树控件：支持把收藏项拖拽到文件夹/分类上完成归类。

    只允许拖动"收藏项"，且只能放到"文件夹"或"分类"节点上（OnItem），
    不能放到收藏项上、也不能拖成顶层的同级项；其余情况直接拒绝。
    drop_handler 为用户拖拽成功后的回调（由主窗口重建收藏数据）。
    """

    def __init__(self, parent=None):
        super(FavoriteTreeWidget, self).__init__(parent)
        self.drop_handler = None

    def dropEvent(self, event):
        # 只处理自身内部的拖拽，外部（如资源管理器）拖入的文件一律忽略
        source_widget = event.source()
        if source_widget is not None and source_widget is not self:
            event.ignore()
            return
        selected = self.selectedItems()
        source = selected[0] if selected else self.currentItem()
        target = self.itemAt(event.pos())
        if not self._can_drop(source, target):
            event.ignore()
            return
        super(FavoriteTreeWidget, self).dropEvent(event)
        if callable(self.drop_handler):
            self.drop_handler()

    def _can_drop(self, source, target):
        if source is None or target is None:
            return False
        if source.data(0, ROLE_TYPE) != "entry":
            return False
        if target.data(0, ROLE_TYPE) not in ("folder", "category"):
            return False
        # 只接受"放到节点上"，拒绝放到节点之间（避免出现顶层同级项）
        if self.dropIndicatorPosition() != QtWidgets.QAbstractItemView.OnItem:
            return False
        return True


class AssetLibrary_Win(QtWidgets.QMainWindow):
    def __init__(self, parent=dcc_interface.get_main_window()):
        super(AssetLibrary_Win, self).__init__(parent=parent)

        self.window_width = 1300
        self.window_height = 960
        self.directory_dialog = None
        self.permission_dialog = None
        self.preference_setting_dialog = None
        self.assets_layout = None
        self.info_widget = None
        self.asset_icon_size = 60
        # 收藏项就地重命名时，用于屏蔽重建收藏树引起的 itemChanged 误触发
        self._favorite_loading = False
        # 资产目录树右键复制的源路径（内部剪贴板）
        self._dir_clipboard_path = ""
        # 缩略图异步加载器（initUI 里创建）与回调用的 key->卡片 映射
        self.thumb_loader = None
        self._thumb_targets = {}
        self._thumb_seq = 0

        # 默认资产根路径：桌面。可在此处改为你的资产目录。
        self.default_path = os.path.join(os.path.expanduser("~"), "Desktop")
        # 代码存放路径：优先用偏好设置里保存的，没有则放在资产根目录下的 code 文件夹
        self.code_path = ""
        # 左下角收藏：{"Asset": [目录...], "Code": [目录...]}
        self.favorites = {ASSET_CATEGORY: [], CODE_CATEGORY: []}
        # level_nums 是"从当前目录再往下钻几层"，所以查询 1 层对应 0
        self.asset_depth = {
            "level_nums": ASSET_QUERY_LEVEL - 1,
            "is_each_folder": True,
            "aims_directories_list": None
        }

        # initial UI
        self.initUI()

    def load_preference_config(self):
        """读取偏好设置配置文件（本地用户目录），读不到就返回空字典
        """
        config_path = utils.local_config_path("preference_config.json")
        if not os.path.exists(config_path):
            return {}
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def initUI(self):
        """build user interface
        """
        # 偏好设置里保存的资产根路径与代码路径
        preference_info = self.load_preference_config()
        saved_path = preference_info.get("default path", "")
        if saved_path and os.path.isdir(saved_path):
            self.default_path = saved_path
        saved_code_path = preference_info.get("code path", "")
        self.code_path = saved_code_path or os.path.join(self.default_path, "code")

        # 缩略图异步加载器：解码缓存放本机（避免多人共享盘写冲突），
        # 缓存边长优先用偏好里的 Thumbnail size
        try:
            thumb_size = int(preference_info.get("Thumbnail size", "") or 256)
        except (ValueError, TypeError):
            thumb_size = 256
        thumb_cache_dir = os.path.join(utils.user_cache_dir(), "thumb_cache")
        self.thumb_loader = utils.ThumbnailLoader(thumb_cache_dir, thumb_size, self)
        self.thumb_loader.loaded.connect(self._on_thumbnail_loaded)

        self.setWindowTitle("AssetLibrary")
        self.setMinimumSize(self.window_width, self.window_height)

        # central widget
        self.main_widget = QtWidgets.QWidget(self)
        self.main_widget.setObjectName("mainwidget")
        self.setCentralWidget(self.main_widget)

        root_layout = QtWidgets.QVBoxLayout(self.main_widget)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # --- file path widget ---
        file_path_widget = QtWidgets.QWidget()
        file_path_widget.setObjectName("file_path_widget")
        file_path_layout = QtWidgets.QHBoxLayout(file_path_widget)
        file_path_layout.setContentsMargins(0, 5, 0, 5)
        file_path_layout.setSpacing(20)

        directory_label = QtWidgets.QLabel("Directory:")
        directory_label.setObjectName("label")
        directory_label.setStyleSheet('font: 12pt "Arial";')
        file_path_layout.addWidget(directory_label)

        self.main_widget.root_path_le = QtWidgets.QLineEdit()
        self.main_widget.root_path_le.setObjectName("root_path_le")
        self.main_widget.root_path_le.setMinimumHeight(30)
        self.main_widget.root_path_le.setStyleSheet(
            'border: 1px solid rgba(255,255,255,50);\n'
            'background-color: rgba(0, 0, 0, 50);\n'
            'font: 14pt "Arial";'
        )
        file_path_layout.addWidget(self.main_widget.root_path_le)

        self.main_widget.root_path_btn = QtWidgets.QPushButton()
        self.main_widget.root_path_btn.setObjectName("root_path_btn")
        file_path_layout.addWidget(self.main_widget.root_path_btn)

        root_layout.addWidget(file_path_widget, 0)

        # --- content widget ---
        content_widget = QtWidgets.QWidget()
        content_widget.setObjectName("content_widget")
        content_layout = QtWidgets.QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        content_layout.addWidget(self._build_left_widget(), 1)
        content_layout.addWidget(self._build_middle_widget(), 3)

        right_widget = QtWidgets.QWidget()
        right_widget.setObjectName("right_widget")
        right_widget.setStyleSheet("QGroup{background-color: rgba(255, 255, 255, 0);}")
        right_layout = QtWidgets.QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(right_widget, 2)

        root_layout.addWidget(content_widget, 20)

        # toolbar and settings action
        toolbar = self.addToolBar("toolBar")
        toolbar.setObjectName("toolBar")
        action_settings = QtWidgets.QAction("Settings", self)
        action_settings.setObjectName("actionSettings")
        action_settings.setToolTip("setting the preference")
        action_settings.setShortcut("Ctrl+Q")
        toolbar.addAction(action_settings)
        self.main_widget.actionSettings = action_settings

        # add icon to buttons
        main_widget_btns = self.main_widget.findChildren(QtWidgets.QPushButton)
        for btn in main_widget_btns:
            icon_name = btn.objectName().replace("_btn", ".png")
            self.set_icon_to_button(icon_name, btn)

        # info widget
        self.populate_information_widget()

        # toolbar
        self.main_widget.actionSettings.triggered.connect(self.show_preference_setting_dialog)
        self.set_icon_to_button("setting.png", self.main_widget.actionSettings)

        # root path
        self.main_widget.root_path_le.setReadOnly(True)
        self.main_widget.root_path_btn.clicked.connect(self.set_root_path)

        # code panel
        self.main_widget.code_view_btn.setCheckable(True)
        self.main_widget.code_view_btn.setIconSize(QtCore.QSize(22, 22))
        self.set_icon_to_button("write.png", self.main_widget.code_view_btn)
        self.main_widget.code_view_btn.clicked.connect(self.switch_code_view)
        self.main_widget.code_panel.set_code_path(self.code_path)
        self.main_widget.asset_search_le.textChanged.connect(self.filter_display)

        # favorite panel
        self.favorites = self.load_favorites()
        self.populate_favorite_tree()
        self.main_widget.add_tag_btn.clicked.connect(self.add_favorite)
        # 单击收藏项直接跳到对应收藏页
        self.main_widget.favorite_tree_widget.itemClicked.connect(self.open_favorite_item)
        # 双击收藏项进入就地重命名；双击分类名则切换到对应界面
        self.main_widget.favorite_tree_widget.itemDoubleClicked.connect(self.on_favorite_double_clicked)
        # 就地编辑完成后把新名字写回配置
        self.main_widget.favorite_tree_widget.itemChanged.connect(self.on_favorite_item_changed)
        self.main_widget.favorite_tree_widget.customContextMenuRequested.connect(
            self.show_favorite_menu)
        # 拖拽收藏项进文件夹/分类后，按树结构同步收藏数据
        self.main_widget.favorite_tree_widget.drop_handler = self.on_favorite_tree_dropped
        # 选中收藏项后按 F2 直接改名
        rename_shortcut = QtWidgets.QShortcut(
            QtGui.QKeySequence("F2"), self.main_widget.favorite_tree_widget)
        rename_shortcut.setContext(QtCore.Qt.WidgetShortcut)
        rename_shortcut.activated.connect(self.rename_favorite_item)

        # tree view
        self.populate_tree_view_ui()
        self.main_widget.directory_treeview.doubleClicked.connect(self.populate_tree_view_ui)
        # 资产目录树右键：复制 / 粘贴文件（夹）
        self.main_widget.directory_treeview.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.main_widget.directory_treeview.customContextMenuRequested.connect(
            self.show_directory_menu)

        self.main_widget.directory_update_btn.clicked.connect(self.populate_tree_view_ui)
        self.main_widget.directory_back_btn.clicked.connect(self.back_to_last_directory)
        self.main_widget.add_directory_btn.clicked.connect(partial(self.get_permission_password_dialog, "add"))
        self.main_widget.delete_directory_btn.clicked.connect(partial(self.get_permission_password_dialog, "delete"))

        # asset widget
        self.main_widget.add_asset_btn.clicked.connect(self.add_asset)

        self.main_widget.asset_status_le.setReadOnly(True)

        self.show()
        self.populate_asset_in_display_widget()

    def _build_left_widget(self):
        """build the left directory/tag panel
        """
        left_widget = QtWidgets.QWidget()
        left_widget.setObjectName("left_widget")
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(0)

        # folder buttons
        folder_widget = QtWidgets.QWidget()
        folder_widget.setObjectName("folder_wiget")
        folder_layout = QtWidgets.QHBoxLayout(folder_widget)
        folder_layout.setContentsMargins(0, 0, 0, 6)
        folder_layout.setSpacing(0)

        self.main_widget.directory_back_btn = QtWidgets.QPushButton()
        self.main_widget.directory_back_btn.setObjectName("directory_back_btn")
        self.main_widget.directory_update_btn = QtWidgets.QPushButton()
        self.main_widget.directory_update_btn.setObjectName("directory_update_btn")
        self.main_widget.add_directory_btn = QtWidgets.QPushButton()
        self.main_widget.add_directory_btn.setObjectName("add_directory_btn")
        self.main_widget.delete_directory_btn = QtWidgets.QPushButton()
        self.main_widget.delete_directory_btn.setObjectName("delete_directory_btn")

        folder_layout.addWidget(self.main_widget.directory_back_btn)
        folder_layout.addWidget(self.main_widget.directory_update_btn)
        folder_layout.addWidget(self.main_widget.add_directory_btn)
        folder_layout.addWidget(self.main_widget.delete_directory_btn)
        folder_layout.addItem(QtWidgets.QSpacerItem(
            40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum))

        left_layout.addWidget(folder_widget)

        # directory tree
        self.main_widget.directory_treeview = QtWidgets.QTreeView()
        self.main_widget.directory_treeview.setObjectName("directory_treeview")
        self.main_widget.directory_treeview.setStyleSheet('font: 12pt "Arial";')
        left_layout.addWidget(self.main_widget.directory_treeview)

        # tag panel
        tag_widget = QtWidgets.QWidget()
        tag_widget.setObjectName("tag_widget")
        tag_layout = QtWidgets.QVBoxLayout(tag_widget)
        tag_layout.setContentsMargins(0, 9, 0, 0)
        tag_layout.setSpacing(0)

        tag_header_widget = QtWidgets.QWidget()
        tag_header_widget.setObjectName("widget_6")
        tag_header_layout = QtWidgets.QHBoxLayout(tag_header_widget)
        tag_header_layout.setContentsMargins(0, 5, 0, 5)

        tag_btn = QtWidgets.QPushButton()
        tag_btn.setObjectName("tag_btn")
        tag_btn.setIconSize(QtCore.QSize(25, 25))
        tag_btn.setToolTip("Favorite")

        favorite_label = QtWidgets.QLabel("Favorite")
        favorite_label.setObjectName("label")
        favorite_label.setStyleSheet('font: 12pt "Arial";')

        self.main_widget.add_tag_btn = QtWidgets.QPushButton()
        self.main_widget.add_tag_btn.setObjectName("add_tag_btn")
        self.main_widget.add_tag_btn.setToolTip("Add the current directory to favorites")

        tag_header_layout.addWidget(tag_btn)
        tag_header_layout.addWidget(favorite_label)
        tag_header_layout.addItem(QtWidgets.QSpacerItem(
            40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum))
        tag_header_layout.addWidget(self.main_widget.add_tag_btn)

        tag_layout.addWidget(tag_header_widget)

        # 收藏树：Asset / Code 两个分类，分类下可建收藏文件夹，双击收藏项打开对应目录
        self.main_widget.favorite_tree_widget = FavoriteTreeWidget()
        self.main_widget.favorite_tree_widget.setObjectName("favorite_tree_widget")
        self.main_widget.favorite_tree_widget.setHeaderHidden(True)
        self.main_widget.favorite_tree_widget.setStyleSheet('font: 11pt "Arial";')
        self.main_widget.favorite_tree_widget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        # 允许把收藏项拖拽到文件夹/分类上完成归类
        self.main_widget.favorite_tree_widget.setDragEnabled(True)
        self.main_widget.favorite_tree_widget.setAcceptDrops(True)
        self.main_widget.favorite_tree_widget.setDropIndicatorShown(True)
        self.main_widget.favorite_tree_widget.setDragDropMode(
            QtWidgets.QAbstractItemView.InternalMove)
        self.main_widget.favorite_tree_widget.setDefaultDropAction(QtCore.Qt.MoveAction)
        tag_layout.addWidget(self.main_widget.favorite_tree_widget)

        left_layout.addWidget(tag_widget)

        return left_widget

    def _build_middle_widget(self):
        """build the middle asset display panel
        """
        middle_widget = QtWidgets.QWidget()
        middle_widget.setObjectName("middle_widget")
        middle_widget.setMinimumWidth(500)

        self.main_widget.middle_layout = QtWidgets.QVBoxLayout(middle_widget)
        self.main_widget.middle_layout.setContentsMargins(0, 0, 0, 0)
        self.main_widget.middle_layout.setSpacing(0)

        # search widget
        search_widget = QtWidgets.QWidget()
        search_widget.setObjectName("search_widget")
        search_layout = QtWidgets.QHBoxLayout(search_widget)
        search_layout.setContentsMargins(0, 0, 20, 6)
        search_layout.setSpacing(6)

        asset_update_btn = QtWidgets.QPushButton()
        asset_update_btn.setObjectName("asset_update_btn")
        move_to_center_btn = QtWidgets.QPushButton()
        move_to_center_btn.setObjectName("move_to_center_btn")

        # 切换到代码界面的按钮，放在搜索栏左侧
        self.main_widget.code_view_btn = QtWidgets.QPushButton()
        self.main_widget.code_view_btn.setObjectName("code_view_btn")
        self.main_widget.code_view_btn.setToolTip("Switch to the code panel")

        self.main_widget.asset_search_le = QtWidgets.QLineEdit()
        self.main_widget.asset_search_le.setObjectName("asset_search_le")
        self.main_widget.asset_search_le.setMinimumHeight(25)
        self.main_widget.asset_search_le.setMaximumWidth(200)
        self.main_widget.asset_search_le.setStyleSheet("border: 0 px;")
        self.main_widget.asset_search_le.setPlaceholderText("Search...")

        self.main_widget.add_asset_btn = QtWidgets.QPushButton()
        self.main_widget.add_asset_btn.setObjectName("add_asset_btn")

        search_layout.addWidget(asset_update_btn)
        search_layout.addWidget(move_to_center_btn)
        search_layout.addWidget(self.main_widget.code_view_btn)
        search_layout.addWidget(self.main_widget.asset_search_le)
        search_layout.addItem(QtWidgets.QSpacerItem(
            40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum))
        search_layout.addWidget(self.main_widget.add_asset_btn)

        self.main_widget.middle_layout.addWidget(search_widget)

        # asset display widget
        asset_display_widget = QtWidgets.QWidget()
        asset_display_widget.setObjectName("asset_display_widget")
        asset_display_layout = QtWidgets.QVBoxLayout(asset_display_widget)
        asset_display_layout.setContentsMargins(0, 0, 0, 0)
        asset_display_layout.setSpacing(0)

        scroll_area = QtWidgets.QScrollArea()
        scroll_area.setObjectName("asset_disaplay_sca")
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        # 保存引用并监听滚动，用于"只加载可视区缩略图"（方案 4）
        self.main_widget.asset_scroll_area = scroll_area
        scroll_area.verticalScrollBar().valueChanged.connect(
            self._update_visible_thumbnails)
        scroll_area.verticalScrollBar().rangeChanged.connect(
            lambda _min, _max: self._update_visible_thumbnails())
        scroll_area.setStyleSheet(
            "QWidget#scrollAreaWidgetContents{background-color: rgba(255,255,255,0);}\n"
            "QScrollArea{border: 0px;}"
        )

        scroll_contents = QtWidgets.QWidget()
        scroll_contents.setObjectName("scrollAreaWidgetContents")
        scroll_contents_layout = QtWidgets.QHBoxLayout(scroll_contents)
        scroll_contents_layout.setContentsMargins(0, 0, 0, 0)
        scroll_contents_layout.setSpacing(0)

        outside_display_widget = QtWidgets.QWidget()
        outside_display_widget.setObjectName("outside_diaplay_widget")
        self.main_widget.outside_diaplay_widget = outside_display_widget
        # 中间资产显示区空白处右键：对当前文件夹执行 Set Project
        outside_display_widget.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        outside_display_widget.customContextMenuRequested.connect(self.show_asset_area_menu)
        outside_layout = QtWidgets.QVBoxLayout(outside_display_widget)
        outside_layout.setContentsMargins(0, 0, 0, 0)
        outside_layout.setSpacing(0)

        display_widget_fixed = QtWidgets.QWidget()
        display_widget_fixed.setObjectName("display_widget_fixed")
        self.main_widget.sa_layout = QtWidgets.QVBoxLayout(display_widget_fixed)
        self.main_widget.sa_layout.setContentsMargins(0, 0, 0, 0)
        self.main_widget.sa_layout.setSpacing(0)

        self.main_widget.display_widget = QtWidgets.QWidget()
        self.main_widget.display_widget.setObjectName("display_widget")
        self.main_widget.sa_layout.addWidget(self.main_widget.display_widget)

        outside_layout.addWidget(display_widget_fixed)
        outside_layout.addItem(QtWidgets.QSpacerItem(
            20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding))

        # scrollbar widget
        scrollbar_widget = QtWidgets.QWidget()
        scrollbar_widget.setObjectName("scollbar_widget")
        scrollbar_widget.setMinimumHeight(30)
        scrollbar_layout = QtWidgets.QHBoxLayout(scrollbar_widget)
        scrollbar_layout.setContentsMargins(0, 5, 0, 0)

        self.main_widget.asset_status_le = QtWidgets.QLineEdit()
        self.main_widget.asset_status_le.setObjectName("asset_status_le")
        self.main_widget.asset_status_le.setMaximumWidth(300)
        self.main_widget.asset_status_le.setStyleSheet(
            "background-color: rgba(255, 255, 255, 0);\nborder: 0px;"
        )
        self.main_widget.display_area_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.main_widget.display_area_slider.setObjectName("display_area_slider")
        self.main_widget.display_area_slider.setRange(30, 120)
        self.main_widget.display_area_slider.setValue(self.asset_icon_size)
        self.main_widget.display_area_slider.setMinimumWidth(100)
        self.main_widget.display_area_slider.valueChanged.connect(self.set_asset_icon_size)

        scrollbar_layout.addWidget(self.main_widget.asset_status_le)
        scrollbar_layout.addWidget(self.main_widget.display_area_slider)

        outside_layout.addWidget(scrollbar_widget)

        scroll_contents_layout.addWidget(outside_display_widget)
        scroll_area.setWidget(scroll_contents)

        asset_display_layout.addWidget(scroll_area)

        # 资产界面与代码界面叠放，通过搜索栏左侧的按钮切换
        self.main_widget.view_stack = QtWidgets.QStackedWidget()
        self.main_widget.view_stack.setObjectName("view_stack")
        self.main_widget.view_stack.addWidget(asset_display_widget)
        self.main_widget.code_panel = code_panel.CodePanelWidget(self)
        self.main_widget.view_stack.addWidget(self.main_widget.code_panel)

        self.main_widget.middle_layout.addWidget(self.main_widget.view_stack)

        return middle_widget

    def set_icon_to_button(self, icon_name, button=None):
        """set icon to the button

        Arguments:
            icon_name -- icon file name in icon directory
            button -- the button you want to set icon to
        """
        icon_dir_path = "icon"
        abs_icon_dir_path = utils.resource_path(icon_dir_path)
        if os.path.exists(abs_icon_dir_path):
            icon_dir_path = abs_icon_dir_path
        icon_path = os.path.join(icon_dir_path, icon_name)
        if not os.path.exists(icon_path):
            return
        try:
            button.setStyleSheet("background-color: rgba(255, 255, 255, 0);\nborder: 0px;")
        except Exception:
            pass
        if not os.path.exists(icon_path):
            return
        try:
            icon = QtGui.QIcon(icon_path)
            button.setIcon(icon)
        except Exception:
            pass

        return icon_path

    def get_all_directory_files(self, path, i):
        """get file in the i depth directory in path

        Arguments:
            path -- the top directory
            i -- 从 path 再往下钻几层去取文件；i=0 表示只取 path 这一层的文件
        """
        if i == 0:
            files_path = utils.find_files_in_path(path)
            for file_path in files_path:
                # 只看文件名最后一个点后的扩展名，忽略路径/文件名中的其它点
                if os.path.splitext(os.path.basename(file_path))[1]:
                    self.asset_files_path.append(file_path)
        else:
            dirs = utils.find_dirs_in_path(path)
            for _dir in dirs:
                new_path = os.path.join(path, _dir)
                self.get_all_directory_files(new_path, i - 1)

    def get_files_in_specific_directory(self, path, dir_list, i):
        dirs = utils.find_dirs_in_path(path)
        for _dir in dirs:
            new_path = os.path.join(path, _dir)
            for sub_dir in dir_list:
                new_path = os.path.join(new_path, sub_dir)
            if os.path.exists(new_path):
                files_path = utils.find_files_in_path(new_path)
                for file_path in files_path:
                    # 只看文件名最后一个点后的扩展名，忽略路径/文件名中的其它点
                    if os.path.splitext(os.path.basename(file_path))[1]:
                        self.asset_files_path.append(file_path)

    def populate_asset_in_display_widget(self):
        """populate assets in the display widget
        """
        self.AssetGroup = utils.AssetButtonGroup()
        self.asset_files_path = []
        if self.asset_depth["is_each_folder"]:
            # get files in every directory of chosen depth
            self.get_all_directory_files(
                self.default_path,
                self.asset_depth["level_nums"])
        else:
            if self.asset_depth["aims_directories_list"]:
                self.get_files_in_specific_directory(
                    self.default_path,
                    self.asset_depth["aims_directories_list"],
                    self.asset_depth["level_nums"])

        # if there are asset buttons in the layout, delete it and then add them
        if self.assets_layout:
            self.main_widget.display_widget.deleteLater()
            self.main_widget.display_widget = QtWidgets.QWidget()
            self.main_widget.display_widget.setObjectName("display_widget")
            self.main_widget.sa_layout.addWidget(self.main_widget.display_widget)

        # add the assets button to the layout
        self.asset_btns = []
        # 旧卡片即将被销毁，清空 key->卡片 映射，令未完成的异步回调自然失效
        self._thumb_targets = {}
        self.assets_layout = flow_layout.FlowLayout(self.main_widget.display_widget)
        default_asset_btn_img_path = "icon/object.png"
        abs_default_asset_btn_img_path = utils.resource_path(default_asset_btn_img_path)
        for ffile in self.asset_files_path:
            name = os.path.basename(ffile)
            file_btn = utils.AssetButton(name, abs_default_asset_btn_img_path, self)
            # 只按最后一个点拆出扩展名，文件名中的其它点保留在名字里
            name, suffix = name.rsplit(".", 1)
            file_btn.asset_path = ffile
            if not file_btn.get_suffix_categorized(suffix):
                continue
            file_btn.set_size(self.asset_icon_size)
            # 计算该资产的缩略图源图并登记，供可视区按需异步加载
            file_btn.thumb_source = utils.resolve_thumb_source(ffile, file_btn.asset_type)
            if file_btn.thumb_source:
                self._thumb_seq += 1
                file_btn.thumb_key = self._thumb_seq
                self._thumb_targets[self._thumb_seq] = file_btn
            self.assets_layout.addWidget(file_btn)
            self.AssetGroup.add_button(file_btn)
            file_btn.clicked.connect(partial(self.populate_information_widget, True))
            # 双击资产在 DCC 中打开
            file_btn.double_clicked.connect(file_btn.open_in_dcc)
            self.asset_btns.append(file_btn)

        # 当前目录没有任何资产、但有子文件夹时，把子文件夹显示为卡片
        if not self.asset_btns:
            self._populate_folder_cards()

        # 布局稳定后再按可视区加载缩略图（方案 3+4）
        QtCore.QTimer.singleShot(0, self._update_visible_thumbnails)

    def _populate_folder_cards(self):
        """在资产区把当前目录下的子文件夹显示为文件夹卡片（可设预览图、双击进入）。"""
        folder_icon = utils.resource_path("icon/folder.png")
        try:
            dirs = utils.find_dirs_in_path(self.default_path)
        except Exception:
            dirs = []
        for dpath in dirs:
            name = os.path.basename(dpath.rstrip("\\/"))
            # 跳过缩略图隐藏目录等
            if name.startswith("."):
                continue
            folder_btn = utils.AssetButton(name, folder_icon, self, is_folder=True)
            folder_btn.asset_path = dpath
            folder_btn.set_size(self.asset_icon_size)
            # 文件夹预览图：sidecar -> 本地 override
            folder_btn.thumb_source = utils.resolve_thumb_source(dpath, None)
            if folder_btn.thumb_source:
                self._thumb_seq += 1
                folder_btn.thumb_key = self._thumb_seq
                self._thumb_targets[self._thumb_seq] = folder_btn
            self.assets_layout.addWidget(folder_btn)
            self.AssetGroup.add_button(folder_btn)
            folder_btn.clicked.connect(partial(self.populate_information_widget, True))
            folder_btn.double_clicked.connect(folder_btn.open_in_dcc)
            self.asset_btns.append(folder_btn)

    def set_asset_icon_size(self, size):
        """update asset icon size based on the display_area_slider value
        """
        self.asset_icon_size = size
        self.populate_asset_in_display_widget()

    def _update_visible_thumbnails(self):
        """只给当前视口内（含少量预取余量）的卡片派发缩略图加载任务（方案 4）。"""
        if self.thumb_loader is None or not getattr(self, "asset_btns", None):
            return
        scroll_area = getattr(self.main_widget, "asset_scroll_area", None)
        if scroll_area is None:
            return
        viewport = scroll_area.viewport()
        view_height = viewport.height()
        margin = max(200, self.asset_icon_size * 3)  # 上下各预取一屏左右
        for btn in self.asset_btns:
            if not btn.thumb_source or btn.thumb_key is None:
                continue
            if btn._thumb_requested:
                continue
            top_left = btn.mapTo(viewport, QtCore.QPoint(0, 0))
            top = top_left.y()
            bottom = top + btn.height()
            if bottom >= -margin and top <= view_height + margin:
                btn._thumb_requested = True
                self.thumb_loader.request(btn.thumb_key, btn.thumb_source)

    def _on_thumbnail_loaded(self, key, image):
        """异步缩略图加载完成：找回对应卡片并设置图片；卡片已重建则忽略。"""
        btn = self._thumb_targets.get(key)
        if btn is None:
            return
        try:
            btn.set_thumbnail_image(image)
        except RuntimeError:
            # 卡片底层 C++ 对象可能已被销毁，忽略
            self._thumb_targets.pop(key, None)

    def mousePressEvent(self, event):
        if self.main_widget.outside_diaplay_widget.underMouse():
            self.populate_information_widget(is_click=False)
            self.AssetGroup.set_selected(None)
        super().mousePressEvent(event)

    def populate_information_widget(self, is_click=False):
        if self.info_widget:
            self.info_widget.deleteLater()
        self.info_widget = QtWidgets.QWidget()
        self.info_widget.setObjectName("InfoWidget")
        self.info_widget.setStyleSheet("""
            #InfoWidget {background-color: rgba(255, 255, 255, 25);}
            }
        """)
        self.info_widget.setFixedHeight(200)
        if is_click:
            proper_td_stylesheet = """
            border: 0px;
            font: 8.5pt "Arial";
            color: rgba(255,255,255,120);
            background-color: rgba(0,0,0, 0);
            """
            info_layout = QtWidgets.QHBoxLayout(self.info_widget)
            info_layout.setSpacing(25)

            # file properties column
            file_properties_layout = QtWidgets.QVBoxLayout()
            file_properties_layout.setSpacing(6)
            file_properties_title = QtWidgets.QLabel("FILE PROPERTIES")
            self.file_properties_td = QtWidgets.QTextEdit()
            self.file_properties_td.setReadOnly(True)
            self.file_properties_td.setStyleSheet(proper_td_stylesheet)
            file_properties_layout.addWidget(file_properties_title)
            file_properties_layout.addWidget(self.file_properties_td)

            # production control
            production_control_layout = QtWidgets.QVBoxLayout()
            production_control_layout.setSpacing(6)
            production_control_title = QtWidgets.QLabel("PRODUCTION CONTROL")

            version_control_widget = QtWidgets.QWidget()
            version_control_layout = QtWidgets.QVBoxLayout(version_control_widget)
            version_control_layout.setMargin(0)

            version_control_label = QtWidgets.QLabel("Version")
            version_control_label.setStyleSheet(proper_td_stylesheet)
            version_choose_layout = QtWidgets.QHBoxLayout()
            self.asset_version_cb = QtWidgets.QComboBox()
            self.asset_version_search_le = QtWidgets.QLineEdit()
            version_choose_layout.addWidget(self.asset_version_cb)
            version_choose_layout.addWidget(self.asset_version_search_le)
            version_control_layout.addWidget(version_control_label)
            version_control_layout.addLayout(version_choose_layout)
            production_control_layout.addWidget(production_control_title)
            production_control_layout.addWidget(version_control_widget)
            production_spacer_item = QtWidgets.QSpacerItem(
                0, 0, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
            production_control_layout.addItem(production_spacer_item)

            # asset properties
            asset_properties_layout = QtWidgets.QVBoxLayout()
            asset_properties_title = QtWidgets.QLabel("ASSET PROPERTIES")
            asset_properties_layout.addWidget(asset_properties_title)
            asset_proper_spacer_item = QtWidgets.QSpacerItem(
                0, 0, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
            asset_properties_layout.addItem(asset_proper_spacer_item)

            # description
            descrip_td_stylesheet = """
            border: 0.5px solid rgba(255,255,255,80);
            font: 8.5pt "Arial";
            color: rgba(255,255,255,120);
            background-color: rgba(0,0,0, 0);
            """
            description_layout = QtWidgets.QVBoxLayout()
            description_layout.setSpacing(6)
            description_title = QtWidgets.QLabel("DESCRIPTION")
            description_td = QtWidgets.QTextEdit()
            description_td.setStyleSheet(descrip_td_stylesheet)
            description_layout.addWidget(description_title)
            description_layout.addWidget(description_td)

            info_layout.addLayout(file_properties_layout)
            info_layout.addLayout(production_control_layout)
            info_layout.addLayout(asset_properties_layout)
            info_layout.addLayout(description_layout)

            self.get_asset_information()

        info_layout = QtWidgets.QVBoxLayout(self.info_widget)
        info_text_label = QtWidgets.QLabel("Select Asset to see the information")
        info_text_label.setAlignment(QtCore.Qt.AlignCenter)
        info_text_label.setStyleSheet("""
            background-color: rgba(255, 255, 255, 0);
            }
        """)
        info_icon_label = QtWidgets.QLabel()
        info_icon_label.setStyleSheet("""
            background-color: rgba(255, 255, 255, 0);
            }
        """)
        icon_path = self.set_icon_to_button("information.png")
        pixmap = QtGui.QPixmap(icon_path)
        pixmap = pixmap.scaled(50, 50)
        info_icon_label.setPixmap(pixmap)
        info_icon_label.setAlignment(QtCore.Qt.AlignCenter)
        info_spacer_item1 = QtWidgets.QSpacerItem(
            0, 0, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        info_layout.addItem(info_spacer_item1)
        info_layout.addWidget(info_text_label)
        info_layout.addWidget(info_icon_label)
        info_spacer_item2 = QtWidgets.QSpacerItem(
            0, 0, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        info_layout.addItem(info_spacer_item2)
        info_layout.setSpacing(15)
        self.main_widget.middle_layout.addWidget(self.info_widget)

    def get_asset_information(self):
        for btn in self.AssetGroup.asset_buttons_list:
            if btn.isCheck():
                asset_info_dic = btn.get_information()
                text = ""
                for key, value in asset_info_dic.items():
                    text += f"{key}: {value}\n"
                self.file_properties_td.setPlainText(text)

    def populate_tree_view_ui(self, QModelIn=None):
        """populate tree view when switching between browsing the catalogue tree
        """
        if QModelIn:
            self.default_path = self.file_sys_model.filePath(QModelIn)
        self.file_sys_model = QtWidgets.QFileSystemModel()
        self.file_sys_model.setFilter(QtCore.QDir.Dirs | QtCore.QDir.NoDotAndDotDot)
        self.file_sys_model.setRootPath(self.default_path)
        self.main_widget.directory_treeview.setModel(self.file_sys_model)
        self.main_widget.directory_treeview.setHeaderHidden(True)
        self.main_widget.directory_treeview.setRootIndex(self.file_sys_model.index(self.default_path))
        for i in [1, 2, 3]:
            self.main_widget.directory_treeview.setColumnHidden(i, True)
        self.main_widget.root_path_le.setText(self.default_path)
        self.populate_asset_in_display_widget()

    def show_preference_setting_dialog(self):
        """showing the preference setting dialog
        """
        preference_dialog = Preference_Dialog(self)

    def add_level_widget(self):
        groups = self.project_hierarchy_dialog.top_widget.findChildren(QtWidgets.QGroupBox)
        group_names_list = []
        for grp in groups:
            grp_name = grp.objectName()
            group_names_list.append(grp_name)
        i = 1
        while True:
            name = "level_{}_grp".format(i)
            if name in group_names_list:
                i += 1
            else:
                break
        new_level_grp = QtWidgets.QGroupBox()
        new_level_grp.setObjectName(name)
        level_grp_layout = QtWidgets.QVBoxLayout(new_level_grp)
        label_layout = QtWidgets.QHBoxLayout()
        spacerItem = QtWidgets.QSpacerItem(
            0, 0, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        label = QtWidgets.QLabel(name.replace("_grp", ""))
        plus_btn = QtWidgets.QPushButton()
        icon_name = "add_level.png"
        self.set_icon_to_button(icon_name, plus_btn)
        plus_btn.clicked.connect(partial(self.add_a_le_to_level, level_grp_layout))
        label_layout.addWidget(label)
        label_layout.addItem(spacerItem)
        label_layout.addWidget(plus_btn)
        level_grp_layout.addLayout(label_layout)
        self.add_a_le_to_level(level_grp_layout)
        self.project_hierarchy_dialog.level_top_layout.insertWidget(i, new_level_grp)
        self.level_wigets_list.append(new_level_grp)

    def add_a_le_to_level(self, layout):
        level_le = QtWidgets.QLineEdit()
        level_le.setStyleSheet("border: 1px solid rgb(100,100,100);")
        layout.addWidget(level_le)

    # main page
    def set_root_path(self):
        current_path = self.default_path
        new_path = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            dir=current_path,
            options=QtWidgets.QFileDialog.Option.ShowDirsOnly
        )
        # 用户取消选择，或选择了"此电脑"等非真实文件系统路径时，
        # 返回空字符串，此时保持原路径不变并直接返回
        if not new_path:
            return
        self.default_path = new_path
        self.populate_tree_view_ui()

    def enter_directory(self, path):
        """进入指定子目录（文件夹卡片双击时调用）。"""
        if not path or not os.path.isdir(path):
            return
        self.default_path = path
        self.populate_tree_view_ui()

    def back_to_last_directory(self):
        new_path = os.path.dirname(self.default_path)
        # 盘符后补上反斜杠，避免拼接出 "F:System Volume Information" 这类错误路径
        if len(new_path) == 2 and new_path[1] == ":":
            new_path += "\\"
        self.default_path = new_path
        self.populate_tree_view_ui()

    # code page
    def switch_code_view(self, checked=False):
        """在资产界面与代码界面之间切换

        Arguments:
            checked -- True 切到代码界面，False 回到资产界面
        """
        is_code_view = bool(checked)
        self.main_widget.view_stack.setCurrentIndex(1 if is_code_view else 0)
        if self.info_widget:
            self.info_widget.setVisible(not is_code_view)

        checked_stylesheet = "background-color: rgba(82, 133, 166, 180);\nborder: 0px;"
        normal_stylesheet = "background-color: rgba(255, 255, 255, 0);\nborder: 0px;"
        self.main_widget.code_view_btn.setStyleSheet(
            checked_stylesheet if is_code_view else normal_stylesheet)

        search_text = self.main_widget.asset_search_le.text()
        if is_code_view:
            self.main_widget.asset_search_le.setPlaceholderText("Search code...")
            code_dir = self.main_widget.code_panel.code_dir()
            if not code_dir or not os.path.isdir(code_dir):
                # 代码目录还不存在时，先让用户指定一个
                self.main_widget.code_panel.choose_code_path()
            else:
                self.main_widget.code_panel.refresh()
            self.main_widget.code_panel.filter_files(search_text)
        else:
            self.main_widget.asset_search_le.setPlaceholderText("Search...")

    def filter_display(self, text):
        """搜索栏输入时，代码界面下过滤 py 文件
        """
        if self.main_widget.code_view_btn.isChecked():
            self.main_widget.code_panel.filter_files(text)

    # favorite page
    def normalize_favorite_entry(self, entry):
        """把一条收藏统一成 {"path": 路径, "name": 显示名}

        兼容旧配置：以前直接存路径字符串，显示名就用目录名。
        """
        if isinstance(entry, dict):
            path = entry.get("path", "")
            name = entry.get("name", "")
        else:
            path = entry
            name = ""
        if not path:
            return None
        if not name:
            name = os.path.basename(path.rstrip("\\/")) or path
        return {"path": path, "name": name}

    def normalize_favorite_node(self, node):
        """把收藏树里的一个节点统一成：收藏项 {"path","name"} 或 收藏文件夹 {"folder","items"}

        文件夹用 "items" 键标识（只支持一层，文件夹里只放收藏项）。
        兼容旧配置：旧数据里都是收藏项（字符串或含 path 的字典），都会被识别为收藏项。
        """
        if self.is_favorite_folder(node):
            name = node.get("folder") or node.get("name") or ""
            if not name:
                return None
            items = (self.normalize_favorite_entry(item)
                     for item in node.get("items", []))
            return {"folder": name, "items": [item for item in items if item]}
        return self.normalize_favorite_entry(node)

    def is_favorite_folder(self, node):
        """收藏文件夹节点以 "items" 键标识
        """
        return isinstance(node, dict) and "items" in node

    def load_favorites(self):
        """读取收藏夹配置文件，读不到就返回两个空分类
        """
        favorites = {ASSET_CATEGORY: [], CODE_CATEGORY: []}
        config_path = utils.local_config_path("favorite_config.json")
        if not os.path.exists(config_path):
            return favorites
        try:
            with open(config_path, "r") as f:
                saved_info = json.load(f)
        except Exception:
            return favorites
        for category in favorites:
            nodes = (self.normalize_favorite_node(node)
                     for node in saved_info.get(category, []))
            favorites[category] = [node for node in nodes if node]
        return favorites

    def save_favorites(self):
        """把收藏夹写回配置文件（本地用户目录）
        """
        config_path = utils.local_config_path("favorite_config.json")
        with open(config_path, "w") as f:
            json.dump(self.favorites, f, indent=4)

    def iter_favorite_entries(self, category):
        """遍历某分类下的所有收藏项（含收藏文件夹内的），产出收藏项 dict
        """
        for node in self.favorites.get(category, []):
            if self.is_favorite_folder(node):
                for entry in node.get("items", []):
                    yield entry
            else:
                yield node

    def find_favorite_entry(self, category, path):
        """按路径找到某分类下的收藏项（含文件夹内的），找不到返回 None
        """
        for entry in self.iter_favorite_entries(category):
            if entry.get("path") == path:
                return entry
        return None

    def find_favorite_folder(self, category, name):
        """按名字找到某分类下的收藏文件夹，找不到返回 None
        """
        for node in self.favorites.get(category, []):
            if self.is_favorite_folder(node) and node.get("folder") == name:
                return node
        return None

    def locate_favorite_entry(self, category, path):
        """定位收藏项，返回 (收藏项, 它所在的列表)；收藏项可能在分类根下或某文件夹内
        """
        for node in self.favorites.get(category, []):
            if self.is_favorite_folder(node):
                for entry in node.get("items", []):
                    if entry.get("path") == path:
                        return entry, node["items"]
            elif node.get("path") == path:
                return node, self.favorites[category]
        return None, None

    def _build_favorite_entry_item(self, entry):
        """由收藏项 dict 生成树的叶子节点
        """
        path = entry.get("path", "")
        item = QtWidgets.QTreeWidgetItem([entry.get("name") or path])
        item.setData(0, ROLE_TYPE, "entry")
        item.setData(0, ROLE_PATH, path)
        item.setToolTip(0, path)
        # 收藏项可编辑、可拖动，但不可作为拖放目标
        item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
                      | QtCore.Qt.ItemIsEditable | QtCore.Qt.ItemIsDragEnabled)
        return item

    def populate_favorite_tree(self):
        """重建左下角收藏树：Asset / Code 两个分类 + 收藏文件夹 + 收藏项
        """
        tree_widget = self.main_widget.favorite_tree_widget
        # 重建期间屏蔽 itemChanged，避免误当作用户改名
        self._favorite_loading = True
        tree_widget.clear()
        category_icons = {
            ASSET_CATEGORY: utils.resource_path("icon/object.png"),
            CODE_CATEGORY: utils.resource_path("icon/write.png")
        }
        folder_icon = utils.resource_path("icon/folder.png")
        for category in (ASSET_CATEGORY, CODE_CATEGORY):
            category_item = QtWidgets.QTreeWidgetItem([category])
            # 分类名不可编辑、不可拖动，但可作为拖放目标（放到分类=放到根下）
            category_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
                                   | QtCore.Qt.ItemIsDropEnabled)
            category_item.setData(0, ROLE_TYPE, "category")
            icon_path = category_icons.get(category, "")
            if icon_path and os.path.exists(icon_path):
                category_item.setIcon(0, QtGui.QIcon(icon_path))
            category_item.setToolTip(0, category)
            for node in self.favorites.get(category, []):
                if self.is_favorite_folder(node):
                    folder_item = QtWidgets.QTreeWidgetItem([node.get("folder", "")])
                    folder_item.setData(0, ROLE_TYPE, "folder")
                    folder_item.setData(0, ROLE_FOLDER, node.get("folder", ""))
                    folder_item.setToolTip(0, "Favorite folder")
                    # 文件夹可编辑、可作为拖放目标，但不能被拖动
                    folder_item.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
                                         | QtCore.Qt.ItemIsEditable | QtCore.Qt.ItemIsDropEnabled)
                    if folder_icon and os.path.exists(folder_icon):
                        folder_item.setIcon(0, QtGui.QIcon(folder_icon))
                    for entry in node.get("items", []):
                        folder_item.addChild(self._build_favorite_entry_item(entry))
                    category_item.addChild(folder_item)
                    folder_item.setExpanded(True)
                else:
                    category_item.addChild(self._build_favorite_entry_item(node))
            tree_widget.addTopLevelItem(category_item)
            category_item.setExpanded(True)
        self._favorite_loading = False

    def get_favorite_category_of_item(self, item):
        """返回收藏项所属分类（沿父链找到顶层分类名），都不是则返回 None
        """
        if item is None:
            return None
        top = item
        while top.parent() is not None:
            top = top.parent()
        category = top.text(0)
        if category in self.favorites:
            return category
        return None

    def current_favorite_category(self):
        """判断当前该收藏到哪个分类：优先用树上选中项，其次看当前界面
        """
        item = self.main_widget.favorite_tree_widget.currentItem()
        category = self.get_favorite_category_of_item(item)
        if category:
            return category
        return CODE_CATEGORY if self.main_widget.code_view_btn.isChecked() else ASSET_CATEGORY

    def current_selected_folder(self, category):
        """当前选中的收藏文件夹节点（须属于给定分类），否则返回 None
        """
        item = self.main_widget.favorite_tree_widget.currentItem()
        if item is None or item.data(0, ROLE_TYPE) != "folder":
            return None
        if self.get_favorite_category_of_item(item) != category:
            return None
        return self.find_favorite_folder(category, item.data(0, ROLE_FOLDER))

    def add_favorite_folder(self, category=None):
        """在收藏栏的某个分类下新建一个收藏文件夹（只支持一层）
        """
        if category not in (ASSET_CATEGORY, CODE_CATEGORY):
            category = self.current_favorite_category()
        name, ok = QtWidgets.QInputDialog.getText(
            self, "New Folder", "Please enter the folder name:", text="New Folder")
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        if self.find_favorite_folder(category, name):
            QtWidgets.QMessageBox.warning(
                self, "New Folder", '"{}" already exists.'.format(name))
            return
        self.favorites.setdefault(category, []).append({"folder": name, "items": []})
        self.save_favorites()
        self.populate_favorite_tree()

    def add_favorite(self, category=None):
        """把当前打开的目录加入收藏

        Arguments:
            category -- "Asset" 收藏当前资产目录，"Code" 收藏当前代码目录；
                        不传则根据选中项或当前界面自动判断
        选中的是收藏文件夹时放进该文件夹，选中分类/空白则放在分类根目录下。
        """
        if category not in (ASSET_CATEGORY, CODE_CATEGORY):
            category = self.current_favorite_category()
        if category == CODE_CATEGORY:
            path = self.main_widget.code_panel.code_dir()
        else:
            path = self.default_path
        if not path:
            QtWidgets.QMessageBox.warning(
                self, "Favorite", "There is no directory to be collected.")
            return
        if not os.path.isdir(path):
            QtWidgets.QMessageBox.warning(
                self, "Favorite", "The directory does not exist:\n{}".format(path))
            return
        if self.find_favorite_entry(category, path):
            QtWidgets.QMessageBox.information(
                self, "Favorite", "The directory is already in the favorites.")
            return
        entry = self.normalize_favorite_entry(path)
        folder = self.current_selected_folder(category)
        if folder is not None:
            folder.setdefault("items", []).append(entry)
        else:
            self.favorites.setdefault(category, []).append(entry)
        self.save_favorites()
        self.populate_favorite_tree()

    def remove_favorite_item(self, item):
        """从收藏里删除某一项（收藏项或收藏文件夹）
        """
        category = self.get_favorite_category_of_item(item)
        if not category or item.parent() is None:
            return
        if item.data(0, ROLE_TYPE) == "folder":
            folder = self.find_favorite_folder(category, item.data(0, ROLE_FOLDER))
            if folder is not None:
                self.favorites[category].remove(folder)
                self.save_favorites()
                self.populate_favorite_tree()
            return
        entry, container = self.locate_favorite_entry(category, item.data(0, ROLE_PATH))
        if entry is not None and container is not None:
            container.remove(entry)
            self.save_favorites()
            self.populate_favorite_tree()

    def rename_favorite_item(self, item=None):
        """改显示名：收藏项只改标签；收藏文件夹则改文件夹名（都不动磁盘上的目录）

        Arguments:
            item -- 要改名的收藏项/文件夹，不传则取树上当前选中项
        """
        if item is None:
            item = self.main_widget.favorite_tree_widget.currentItem()
        category = self.get_favorite_category_of_item(item)
        if not category or item.parent() is None:
            return
        if item.data(0, ROLE_TYPE) == "folder":
            folder = self.find_favorite_folder(category, item.data(0, ROLE_FOLDER))
            if not folder:
                return
            new_name, ok = QtWidgets.QInputDialog.getText(
                self, "Rename", "Please enter the new name:", text=folder["folder"])
            if not ok or not new_name.strip():
                return
            new_name = new_name.strip()
            if new_name == folder["folder"]:
                return
            if self.find_favorite_folder(category, new_name):
                QtWidgets.QMessageBox.warning(
                    self, "Rename", '"{}" already exists.'.format(new_name))
                return
            folder["folder"] = new_name
            self.save_favorites()
            self.populate_favorite_tree()
            return
        entry = self.find_favorite_entry(category, item.data(0, ROLE_PATH))
        if not entry:
            return
        new_name, ok = QtWidgets.QInputDialog.getText(
            self, "Rename", "Please enter the new name:", text=entry["name"])
        if not ok or not new_name.strip():
            return
        entry["name"] = new_name.strip()
        self.save_favorites()
        self.populate_favorite_tree()

    def reset_favorite_name(self, item=None):
        """把收藏项的显示名恢复成目录名
        """
        if item is None:
            item = self.main_widget.favorite_tree_widget.currentItem()
        category = self.get_favorite_category_of_item(item)
        if not category or item.parent() is None:
            return
        entry = self.find_favorite_entry(category, item.data(0, ROLE_PATH))
        if not entry:
            return
        entry["name"] = os.path.basename(entry["path"].rstrip("\\/")) or entry["path"]
        self.save_favorites()
        self.populate_favorite_tree()

    def on_favorite_double_clicked(self, item=None, column=0):
        """双击收藏树：
        - 双击分类名（Asset / Code）：切换到对应界面；
        - 双击具体收藏项：进入就地编辑，直接重命名标签。
        """
        if item is None:
            return
        if item.parent() is None:
            category = self.get_favorite_category_of_item(item)
            if category:
                self.switch_to_category_view(category)
            return
        # 具体收藏项，进入就地编辑重命名
        self.main_widget.favorite_tree_widget.editItem(item, 0)

    def on_favorite_item_changed(self, item=None, column=0):
        """就地编辑完成后把新名字写回配置；空名字恢复原名，重名则拒绝。
        """
        if self._favorite_loading:
            return
        if item is None or item.parent() is None:
            return
        category = self.get_favorite_category_of_item(item)
        if not category:
            return
        new_name = item.text(0).strip()
        if item.data(0, ROLE_TYPE) == "folder":
            folder = self.find_favorite_folder(category, item.data(0, ROLE_FOLDER))
            if not folder:
                return
            if not new_name or self.find_favorite_folder(category, new_name):
                # 空名字或与其它文件夹重名：恢复原名
                self._favorite_loading = True
                item.setText(0, folder["folder"])
                self._favorite_loading = False
                return
            if new_name == folder["folder"]:
                return
            folder["folder"] = new_name
            self._favorite_loading = True
            item.setData(0, ROLE_FOLDER, new_name)
            self._favorite_loading = False
            self.save_favorites()
            return
        entry = self.find_favorite_entry(category, item.data(0, ROLE_PATH))
        if not entry:
            return
        if not new_name:
            # 名字为空则恢复原名，不写配置
            self._favorite_loading = True
            item.setText(0, entry["name"])
            self._favorite_loading = False
            return
        if new_name == entry["name"]:
            return
        entry["name"] = new_name
        self.save_favorites()

    def open_favorite_item(self, item=None, column=0):
        """单击收藏项：Code 打开对应代码目录的代码界面，Asset 跳到对应资产目录；
        单击分类名切到该分类界面；单击收藏文件夹展开它
        """
        if item is None:
            item = self.main_widget.favorite_tree_widget.currentItem()
        category = self.get_favorite_category_of_item(item)
        if not category:
            return
        if item.parent() is None:
            # 单击的是 Asset / Code 分类本身，只切界面，不改当前目录
            self.switch_to_category_view(category)
            return
        if item.data(0, ROLE_TYPE) == "folder":
            item.setExpanded(True)
            return
        path = item.data(0, ROLE_PATH)
        if not path or not os.path.isdir(path):
            QtWidgets.QMessageBox.warning(
                self, "Favorite", "The directory does not exist:\n{}".format(path))
            return

        if category == CODE_CATEGORY:
            # 先把代码目录设好再切界面：不然 switch_code_view 会因为目录无效而弹出选择目录窗口
            self.code_path = path
            self.main_widget.code_panel.set_code_path(path)
        else:
            self.default_path = path
        self.switch_to_category_view(category)

    def on_favorite_tree_dropped(self):
        """收藏树内拖拽完成后，按树的新结构重建收藏数据并保存
        """
        tree_widget = self.main_widget.favorite_tree_widget
        new_favorites = {ASSET_CATEGORY: [], CODE_CATEGORY: []}
        for i in range(tree_widget.topLevelItemCount()):
            category_item = tree_widget.topLevelItem(i)
            category = category_item.text(0)
            if category not in new_favorites:
                continue
            nodes = []
            for j in range(category_item.childCount()):
                child = category_item.child(j)
                if child.data(0, ROLE_TYPE) == "folder":
                    items = []
                    for k in range(child.childCount()):
                        leaf = child.child(k)
                        path = leaf.data(0, ROLE_PATH)
                        if path:
                            items.append({"path": path, "name": leaf.text(0)})
                    nodes.append({"folder": child.text(0), "items": items})
                else:
                    path = child.data(0, ROLE_PATH)
                    if path:
                        nodes.append({"path": path, "name": child.text(0)})
            new_favorites[category] = nodes
        self.favorites = new_favorites
        self.save_favorites()

    def switch_to_category_view(self, category):
        """切到某个收藏分类对应的界面

        Asset 回到资产界面并刷新目录树；Code 切到代码界面，代码目录还没设时
        用该分类下第一条可用收藏兜底，避免弹出选择目录窗口。
        """
        if category == CODE_CATEGORY:
            code_dir = self.main_widget.code_panel.code_dir()
            if not code_dir or not os.path.isdir(code_dir):
                for entry in self.iter_favorite_entries(CODE_CATEGORY):
                    path = entry.get("path", "")
                    if path and os.path.isdir(path):
                        self.code_path = path
                        self.main_widget.code_panel.set_code_path(path)
                        break
            self.main_widget.code_view_btn.setChecked(True)
            self.switch_code_view(True)
        else:
            self.main_widget.code_view_btn.setChecked(False)
            self.switch_code_view(False)
            self.populate_tree_view_ui()

    def show_favorite_menu(self, pos):
        """收藏树右键菜单
        """
        tree_widget = self.main_widget.favorite_tree_widget
        item = tree_widget.itemAt(pos)
        if item is not None:
            # 让右键的节点成为当前选中项，便于"添加到选中文件夹"等操作定位
            tree_widget.setCurrentItem(item)
        category = self.get_favorite_category_of_item(item)

        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(utils.AssetButton.menu_qss_stylesheet)
        menu.setStyle(utils.MenuCustomStyle())

        # 新建收藏文件夹（放到右键所在分类；空白处则按当前分类）
        menu.addAction(
            "New Folder",
            partial(self.add_favorite_folder, category or self.current_favorite_category()))

        if category:
            menu.addAction("Add {} Directory".format(category), partial(self.add_favorite, category))
        else:
            menu.addAction("Add Current Directory", self.add_favorite)

        if item is not None and item.parent() is not None:
            menu.addSeparator()
            if item.data(0, ROLE_TYPE) == "folder":
                menu.addAction("Rename", partial(self.rename_favorite_item, item))
                menu.addAction("Remove", partial(self.remove_favorite_item, item))
            else:
                menu.addAction("Open", partial(self.open_favorite_item, item))
                menu.addAction(
                    "Open in Explorer",
                    partial(utils.open_folder_of_given_path, item.data(0, ROLE_PATH)))
                menu.addSeparator()
                menu.addAction("Rename", partial(self.rename_favorite_item, item))
                menu.addAction("Reset Name", partial(self.reset_favorite_name, item))
                menu.addAction("Remove", partial(self.remove_favorite_item, item))

        menu.addSeparator()
        menu.addAction("Refresh", self.populate_favorite_tree)
        menu.exec_(QtGui.QCursor.pos())

    # asset display area set project
    def show_asset_area_menu(self, pos):
        """中间资产显示区空白处右键菜单：Set Project / 粘贴剪贴板文件
        """
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(utils.AssetButton.menu_qss_stylesheet)
        menu.setStyle(utils.MenuCustomStyle())
        menu.addAction("New Folder", self.create_new_folder)
        menu.addSeparator()
        menu.addAction("Set Project", self.set_project_to_current_dir)
        menu.addSeparator()
        paste_action = menu.addAction("Paste", self.paste_from_clipboard)
        # 剪贴板里没有文件时把 Paste 置灰
        paste_action.setEnabled(bool(self.get_clipboard_file_paths()))
        menu.exec_(QtGui.QCursor.pos())

    def get_clipboard_file_paths(self):
        """读取系统剪贴板里的本地文件路径列表（无则返回空列表）
        """
        clipboard = QtWidgets.QApplication.clipboard()
        mime_data = clipboard.mimeData()
        if not mime_data or not mime_data.hasUrls():
            return []
        paths = []
        for url in mime_data.urls():
            local = url.toLocalFile()
            if local and os.path.exists(local):
                paths.append(local)
        return paths

    def paste_from_clipboard(self):
        """把系统剪贴板里的文件（夹）粘贴到当前打开的目录
        """
        src_paths = self.get_clipboard_file_paths()
        if not src_paths:
            QtWidgets.QMessageBox.warning(self, "Paste", "There is no file in the clipboard.")
            return
        dst_dir = self.default_path
        if not dst_dir or not os.path.isdir(dst_dir):
            QtWidgets.QMessageBox.warning(self, "Paste", "The target directory is invalid.")
            return
        failed = []
        for src in src_paths:
            base_name = os.path.basename(src.rstrip("\\/"))
            dst = self._unique_dest_path(dst_dir, base_name)
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
            except Exception as e:
                failed.append("{}: {}".format(base_name, e))
        self.populate_tree_view_ui()
        if failed:
            QtWidgets.QMessageBox.warning(
                self, "Paste", "Some items failed to paste:\n" + "\n".join(failed))

    def create_new_folder(self):
        """在当前打开的目录下新建一个文件夹
        """
        dst_dir = self.default_path
        if not dst_dir or not os.path.isdir(dst_dir):
            QtWidgets.QMessageBox.warning(
                self, "New Folder", "The current directory is invalid.")
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self, "New Folder", "Please enter the folder name:", text="New Folder")
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        new_path = os.path.join(dst_dir, name)
        if os.path.exists(new_path):
            QtWidgets.QMessageBox.warning(
                self, "New Folder", '"{}" already exists.'.format(name))
            return
        try:
            os.makedirs(new_path)
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, "New Folder", "Failed to create the folder:\n{}".format(e))
            return
        self.populate_tree_view_ui()

    def set_project_to_current_dir(self):
        """把当前打开的目录设为 DCC 的工程目录
        """
        path = self.default_path
        if not path or not os.path.isdir(path):
            QtWidgets.QMessageBox.warning(
                self, "Set Project", "The current directory is invalid.")
            return
        try:
            dcc_interface.set_project(path)
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, "Set Project", "Set Project failed:\n{}".format(e))
            return
        self.main_widget.asset_status_le.setText("Project: {}".format(path))

    # directory tree copy / paste
    def show_directory_menu(self, pos):
        """资产目录树右键菜单：复制 / 粘贴文件（夹）
        """
        tree = self.main_widget.directory_treeview
        index = tree.indexAt(pos)

        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(utils.AssetButton.menu_qss_stylesheet)
        menu.setStyle(utils.MenuCustomStyle())

        has_clipboard = bool(self._dir_clipboard_path) and os.path.exists(self._dir_clipboard_path)

        if index.isValid():
            path = self.file_sys_model.filePath(index)
            menu.addAction("Rename", partial(self.rename_directory_item, path))
            menu.addAction("Copy", partial(self.copy_directory_item, path))
            paste_action = menu.addAction("Paste", partial(self.paste_directory_item, path))
            paste_action.setEnabled(has_clipboard)
            menu.addSeparator()
            explorer_path = path if os.path.isdir(path) else os.path.dirname(path)
            menu.addAction("Open in Explorer",
                           partial(utils.open_folder_of_given_path, explorer_path))
        else:
            # 空白处右键：粘贴到当前根目录
            paste_action = menu.addAction("Paste", partial(self.paste_directory_item, None))
            paste_action.setEnabled(has_clipboard)

        menu.addSeparator()
        menu.addAction("Refresh", self.populate_tree_view_ui)
        menu.exec_(QtGui.QCursor.pos())

    def rename_directory_item(self, path):
        """弹输入框，将文件（夹）就地重命名
        """
        if not path or not os.path.exists(path):
            return
        old_name = os.path.basename(path.rstrip("\\/"))
        new_name, ok = QtWidgets.QInputDialog.getText(
            self, "Rename", "New name:", text=old_name)
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name or new_name == old_name:
            return
        dst = os.path.join(os.path.dirname(path), new_name)
        if os.path.exists(dst):
            QtWidgets.QMessageBox.warning(
                self, "Rename", '"{}" already exists.'.format(new_name))
            return
        try:
            os.rename(path, dst)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Rename", "Rename failed:\n{}".format(e))
            return
        self.populate_tree_view_ui()

    def copy_directory_item(self, path):
        """把选中的文件（夹）记入内部剪贴板，同时写入系统剪贴板
        """
        if not path or not os.path.exists(path):
            return
        self._dir_clipboard_path = path
        # 同步写入系统剪贴板，方便在资源管理器里直接粘贴
        clipboard = QtWidgets.QApplication.clipboard()
        mime_data = QtCore.QMimeData()
        mime_data.setUrls([QtCore.QUrl.fromLocalFile(path)])
        clipboard.setMimeData(mime_data)

    def paste_directory_item(self, target_path=None):
        """把内部剪贴板里的文件（夹）粘贴到目标目录
        """
        src = self._dir_clipboard_path
        if not src or not os.path.exists(src):
            QtWidgets.QMessageBox.warning(self, "Paste", "There is nothing to paste.")
            return
        # 确定目标目录：目录则粘进去，文件则粘到其所在目录，空白处则粘到当前根目录
        if target_path and os.path.isdir(target_path):
            dst_dir = target_path
        elif target_path and os.path.isfile(target_path):
            dst_dir = os.path.dirname(target_path)
        else:
            dst_dir = self.default_path
        if not dst_dir or not os.path.isdir(dst_dir):
            QtWidgets.QMessageBox.warning(self, "Paste", "The target directory is invalid.")
            return
        base_name = os.path.basename(src.rstrip("\\/"))
        dst = self._unique_dest_path(dst_dir, base_name)
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Paste", "Paste failed:\n{}".format(e))
            return
        self.populate_tree_view_ui()

    def _unique_dest_path(self, dst_dir, base_name):
        """在 dst_dir 下为 base_name 生成不冲突的目标路径
        """
        dst = os.path.join(dst_dir, base_name)
        if not os.path.exists(dst):
            return dst
        name, ext = os.path.splitext(base_name)
        i = 1
        while True:
            suffix = "_copy" if i == 1 else "_copy{}".format(i)
            candidate = os.path.join(dst_dir, "{}{}{}".format(name, suffix, ext))
            if not os.path.exists(candidate):
                return candidate
            i += 1

    def get_input_dialog(self):
        dialog = QtWidgets.QDialog(self)
        dialog.setObjectName("Dialog")
        dialog.setWindowTitle("Add Directory")
        dialog.setModal(QtCore.Qt.ApplicationModal)

        vertical_layout = QtWidgets.QVBoxLayout(dialog)

        horizontal_layout = QtWidgets.QHBoxLayout()
        horizontal_layout.setStretch(0, 3)
        horizontal_layout.setStretch(1, 2)

        label = QtWidgets.QLabel("Please enter the name:")
        label.setObjectName("label")
        dir_name_le = QtWidgets.QLineEdit()
        dir_name_le.setObjectName("dir_name_le")

        horizontal_layout.addWidget(label)
        horizontal_layout.addWidget(dir_name_le)
        vertical_layout.addLayout(horizontal_layout)

        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        button_box.setObjectName("buttonBox")
        vertical_layout.addWidget(button_box)

        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)

        dialog.dir_name_le = dir_name_le
        self.input_dialog = dialog
        self.input_dialog.accepted.connect(self.get_input_name)
        self.input_dialog.exec_()

    def get_input_name(self):
        if self.input_dialog:
            self.input_name = self.input_dialog.dir_name_le.text()

    def get_permission_password_dialog(self, to_deal_with):
        dialog = QtWidgets.QDialog(self)
        dialog.setObjectName("Dialog")
        dialog.setWindowTitle("Permission password")
        dialog.setModal(QtCore.Qt.ApplicationModal)

        vertical_layout = QtWidgets.QVBoxLayout(dialog)
        vertical_layout.setSpacing(20)

        label = QtWidgets.QLabel("Please enter the permission password:")
        label.setObjectName("label")
        vertical_layout.addWidget(label)

        password_le = QtWidgets.QLineEdit()
        password_le.setObjectName("password_le")
        vertical_layout.addWidget(password_le)

        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        button_box.setObjectName("dialog_bb")
        vertical_layout.addWidget(button_box)

        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)

        dialog.password_le = password_le
        self.permission_dialog = dialog

        if to_deal_with == "add":
            self.permission_dialog.accepted.connect(self.add_directory)
        elif to_deal_with == "delete":
            self.permission_dialog.accepted.connect(self.remove_directory)

        self.permission_dialog.exec_()

    def add_directory(self):
        password = self.permission_dialog.password_le.text()
        if password == "2121":
            self.get_input_dialog()
            self.directory_name = self.input_name
            directory_path = os.path.join(self.default_path, self.directory_name)
            os.makedirs(directory_path)
        else:
            QtWidgets.QMessageBox.warning(self,
                                          "Input Error",
                                          "Password is not correct")

    def remove_directory(self):
        password = self.permission_dialog.password_le.text()
        if password != "2121":
            QtWidgets.QMessageBox.warning(self,
                                          "Input Error",
                                          "Password is not correct")
            return
        current_selected_index = self.main_widget.directory_treeview.currentIndex()
        remove_path = self.file_sys_model.filePath(current_selected_index)
        try:
            os.removedirs(remove_path)
        except Exception:
            shutil.rmtree(remove_path)

    def add_asset(self):
        # 代码界面下，"+" 按钮用于新建 py 文件
        if self.main_widget.code_view_btn.isChecked():
            self.main_widget.code_panel.add_py_file()


class Preference_Dialog(QtWidgets.QMainWindow):
    def __init__(self, parent):
        super().__init__(parent=parent)
        self.parent = parent
        # 偏好写到本地用户目录（共享盘只读，且多人不互相覆盖）
        self.config_file_path = utils.local_config_path("preference_config.json")
        self.init_ui()

    def init_ui(self):
        self.preference_setting_dialog = self._build_preference_dialog()
        self.preference_setting_dialog.setWindowTitle("Preference Settings")

        preference_widget_btns = (
            self.preference_setting_dialog.findChildren(QtWidgets.QPushButton)
            + self.preference_setting_dialog.findChildren(QtWidgets.QRadioButton)
        )
        for btn in preference_widget_btns:
            icon_name = btn.objectName().replace("_btn", ".png")
            self.parent.set_icon_to_button(icon_name, btn)

        # 代码路径浏览按钮的图标
        self.parent.set_icon_to_button(
            "root_path.png", self.preference_setting_dialog.code_path_browse_btn)

        # preference setting tab
        self.init_preference_info()
        self.preference_setting_dialog.preference_save_btn.clicked.connect(self.save_preference_info)
        self.preference_setting_dialog.code_path_browse_btn.clicked.connect(self.set_code_path)
        # create project tab
        self.preference_setting_dialog.add_project_type_btn.clicked.connect(self.set_project_hierarchy_dialog)
        self.preference_setting_dialog.setModal(QtCore.Qt.ApplicationModal)
        self.preference_setting_dialog.exec_()

    def _build_preference_dialog(self):
        """build the preference settings dialog
        """
        dialog = QtWidgets.QDialog(self)
        dialog.setObjectName("Dialog")

        dialog_layout = QtWidgets.QVBoxLayout(dialog)

        tab_widget = QtWidgets.QTabWidget()
        tab_widget.setObjectName("tabWidget")
        tab_widget.setTabPosition(QtWidgets.QTabWidget.South)
        dialog_layout.addWidget(tab_widget)

        # ---- Preference tab ----
        setting_tab = QtWidgets.QWidget()
        setting_tab.setObjectName("setting_tab")
        setting_layout = QtWidgets.QVBoxLayout(setting_tab)
        setting_layout.setContentsMargins(0, 0, 0, 9)
        setting_layout.setSpacing(0)
        tab_widget.addTab(setting_tab, "Preference")

        pref_widget = QtWidgets.QWidget()
        pref_widget.setObjectName("widget")
        pref_layout = QtWidgets.QVBoxLayout(pref_widget)
        pref_layout.setSpacing(20)

        thumbnails_grp = QtWidgets.QGroupBox("Thumbnails")
        thumbnails_grp.setObjectName("thumbnails_grp")
        thumbnails_layout = QtWidgets.QHBoxLayout(thumbnails_grp)
        thumbnails_layout.addWidget(QtWidgets.QLabel("Thumbnails size:"))

        dialog.thumbnail_size_le = QtWidgets.QLineEdit()
        dialog.thumbnail_size_le.setObjectName("thumbnail_size_le")
        dialog.thumbnail_size_le.setMaximumWidth(100)
        thumbnails_layout.addWidget(dialog.thumbnail_size_le)

        thumbnails_layout.addWidget(QtWidgets.QLabel("Thumbnails quality"))

        dialog.thumbnail_quality_cb = QtWidgets.QComboBox()
        dialog.thumbnail_quality_cb.setObjectName("thumbnail_quality_cb")
        for i in range(1, 6):
            dialog.thumbnail_quality_cb.addItem(str(i))
        thumbnails_layout.addWidget(dialog.thumbnail_quality_cb)
        thumbnails_layout.addItem(QtWidgets.QSpacerItem(
            40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum))
        pref_layout.addWidget(thumbnails_grp)

        language_grp = QtWidgets.QGroupBox("Language")
        language_grp.setObjectName("language_grp")
        language_layout = QtWidgets.QHBoxLayout(language_grp)
        dialog.eng_rb = QtWidgets.QRadioButton("English")
        dialog.eng_rb.setObjectName("eng_rb")
        dialog.eng_rb.setChecked(True)
        dialog.ch_rb = QtWidgets.QRadioButton("Chinese")
        dialog.ch_rb.setObjectName("ch_rb")
        language_layout.addWidget(dialog.eng_rb)
        language_layout.addWidget(dialog.ch_rb)
        language_layout.addItem(QtWidgets.QSpacerItem(
            40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum))
        pref_layout.addWidget(language_grp)

        project_grp = QtWidgets.QGroupBox("Default Project Root Path")
        project_grp.setObjectName("project_grp")
        project_layout = QtWidgets.QHBoxLayout(project_grp)
        dialog.project_root_path_le = QtWidgets.QLineEdit()
        dialog.project_root_path_le.setObjectName("project_root_path_le")
        dialog.project_root_path_le.setMinimumHeight(20)
        project_layout.addWidget(dialog.project_root_path_le)
        pref_layout.addWidget(project_grp)

        code_grp = QtWidgets.QGroupBox("Code Root Path")
        code_grp.setObjectName("code_grp")
        code_layout = QtWidgets.QHBoxLayout(code_grp)
        dialog.code_root_path_le = QtWidgets.QLineEdit()
        dialog.code_root_path_le.setObjectName("code_root_path_le")
        dialog.code_root_path_le.setMinimumHeight(20)
        dialog.code_root_path_le.setPlaceholderText("Where the .py files are stored")
        code_layout.addWidget(dialog.code_root_path_le)
        dialog.code_path_browse_btn = QtWidgets.QPushButton()
        dialog.code_path_browse_btn.setObjectName("code_path_browse_btn")
        dialog.code_path_browse_btn.setMaximumWidth(30)
        code_layout.addWidget(dialog.code_path_browse_btn)
        pref_layout.addWidget(code_grp)

        pref_layout.addItem(QtWidgets.QSpacerItem(
            20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding))
        setting_layout.addWidget(pref_widget)

        button_widget = QtWidgets.QWidget()
        button_widget.setObjectName("widget_5")
        button_layout = QtWidgets.QHBoxLayout(button_widget)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(6)
        button_layout.addItem(QtWidgets.QSpacerItem(
            40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum))

        preference_reset_btn = QtWidgets.QPushButton("Reset")
        preference_reset_btn.setObjectName("preference_reset_btn")
        dialog.preference_save_btn = QtWidgets.QPushButton("Save")
        dialog.preference_save_btn.setObjectName("preference_save_btn")
        button_layout.addWidget(preference_reset_btn)
        button_layout.addWidget(dialog.preference_save_btn)

        setting_layout.addWidget(button_widget)

        # ---- CreateProject tab ----
        create_project_tab = QtWidgets.QWidget()
        create_project_tab.setObjectName("create_project_tab")
        create_project_layout = QtWidgets.QVBoxLayout(create_project_tab)
        create_project_layout.setContentsMargins(0, 0, 0, 0)
        create_project_layout.setSpacing(0)
        tab_widget.addTab(create_project_tab, "CreatePorject")

        create_h_layout = QtWidgets.QHBoxLayout()
        create_h_layout.setSpacing(10)
        create_h_layout.setStretch(0, 2)
        create_h_layout.setStretch(1, 3)
        create_project_layout.addLayout(create_h_layout)

        left_col = QtWidgets.QWidget()
        left_col.setObjectName("widget_4")
        left_col_layout = QtWidgets.QVBoxLayout(left_col)

        dialog.add_project_type_btn = QtWidgets.QPushButton()
        dialog.add_project_type_btn.setObjectName("add_project_type_btn")
        dialog.add_project_type_btn.setMaximumWidth(20)
        left_col_layout.addWidget(dialog.add_project_type_btn)

        type_widget = QtWidgets.QWidget()
        type_widget.setObjectName("widget_2")
        type_widget.setStyleSheet("border: 1px solid rgb(100,100,100);")
        type_grid = QtWidgets.QGridLayout(type_widget)
        type_grid.setContentsMargins(10, 10, 10, 10)
        type_grid.setHorizontalSpacing(10)

        game_btn = QtWidgets.QRadioButton()
        game_btn.setObjectName("Game_btn")
        game_btn.setStyleSheet("border: 0px;")
        game_btn.setIconSize(QtCore.QSize(30, 30))
        tvshow_btn = QtWidgets.QRadioButton()
        tvshow_btn.setObjectName("TVshow_btn")
        tvshow_btn.setStyleSheet("border: 0px;")
        tvshow_btn.setIconSize(QtCore.QSize(30, 30))
        tvshow_btn.setChecked(True)

        type_grid.addWidget(game_btn, 0, 0)
        type_grid.addWidget(tvshow_btn, 0, 1)
        type_grid.addItem(QtWidgets.QSpacerItem(
            20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding), 2, 0)

        left_col_layout.addWidget(type_widget)
        create_h_layout.addWidget(left_col)

        right_col = QtWidgets.QWidget()
        right_col.setObjectName("widget_3")
        right_col_layout = QtWidgets.QVBoxLayout(right_col)
        right_col_layout.setSpacing(10)
        right_col_layout.addItem(QtWidgets.QSpacerItem(
            20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding))

        loc_layout = QtWidgets.QHBoxLayout()
        loc_label = QtWidgets.QLabel("Project Location")
        loc_label.setMinimumWidth(80)
        loc_layout.addWidget(loc_label)
        dialog.cr_pj_loc_le = QtWidgets.QLineEdit()
        dialog.cr_pj_loc_le.setObjectName("cr_pj_loc_le")
        loc_layout.addWidget(dialog.cr_pj_loc_le)
        dialog.cr_pj_location_btn = QtWidgets.QPushButton()
        dialog.cr_pj_location_btn.setObjectName("cr_pj_location_btn")
        loc_layout.addWidget(dialog.cr_pj_location_btn)
        right_col_layout.addLayout(loc_layout)

        name_layout = QtWidgets.QHBoxLayout()
        name_label = QtWidgets.QLabel("Project Name")
        name_label.setMinimumWidth(80)
        name_layout.addWidget(name_label)
        dialog.cr_pj_name_le = QtWidgets.QLineEdit()
        dialog.cr_pj_name_le.setObjectName("cr_pj_name_le")
        name_layout.addWidget(dialog.cr_pj_name_le)
        right_col_layout.addLayout(name_layout)

        dialog.cr_pj_create_btn = QtWidgets.QPushButton("Create")
        dialog.cr_pj_create_btn.setObjectName("cr_pj_create_btn")
        dialog.cr_pj_create_btn.setStyleSheet(
            'background-color: rgb(113, 162, 188);\nfont: 75 14pt "Arial";')
        right_col_layout.addWidget(dialog.cr_pj_create_btn)
        right_col_layout.addItem(QtWidgets.QSpacerItem(
            20, 40, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding))

        create_h_layout.addWidget(right_col)

        # ---- OpenProject tab ----
        open_project_tab = QtWidgets.QWidget()
        open_project_tab.setObjectName("open_project_tab")
        open_project_layout = QtWidgets.QVBoxLayout(open_project_tab)
        tab_widget.addTab(open_project_tab, "OpenProject")

        dialog.tableView = QtWidgets.QTableView()
        dialog.tableView.setObjectName("tableView")
        open_project_layout.addWidget(dialog.tableView)

        op_loc_layout = QtWidgets.QHBoxLayout()
        op_loc_label = QtWidgets.QLabel("project Location:")
        op_loc_label.setMinimumWidth(120)
        op_loc_label.setStyleSheet('font: 12pt "Arial";')
        op_loc_layout.addWidget(op_loc_label)
        dialog.op_pj_loc_le = QtWidgets.QLineEdit()
        dialog.op_pj_loc_le.setObjectName("op_pj_loc_le")
        op_loc_layout.addWidget(dialog.op_pj_loc_le)
        dialog.project_browse_btn = QtWidgets.QPushButton()
        dialog.project_browse_btn.setObjectName("project_browse_btn")
        dialog.project_browse_btn.setMinimumWidth(50)
        root_path_icon = utils.resource_path("icon/root_path.png")
        if os.path.exists(root_path_icon):
            dialog.project_browse_btn.setIcon(QtGui.QIcon(root_path_icon))
        op_loc_layout.addWidget(dialog.project_browse_btn)
        open_project_layout.addLayout(op_loc_layout)

        op_name_layout = QtWidgets.QHBoxLayout()
        op_name_label = QtWidgets.QLabel("project name:")
        op_name_label.setMinimumWidth(120)
        op_name_label.setStyleSheet('font: 12pt "Arial";')
        op_name_layout.addWidget(op_name_label)
        dialog.op_pj_name_le = QtWidgets.QLineEdit()
        dialog.op_pj_name_le.setObjectName("op_pj_name_le")
        op_name_layout.addWidget(dialog.op_pj_name_le)
        open_project_layout.addLayout(op_name_layout)

        dialog.create_project_btn = QtWidgets.QPushButton("Open")
        dialog.create_project_btn.setObjectName("create_project_btn")
        dialog.create_project_btn.setMinimumWidth(100)
        dialog.create_project_btn.setStyleSheet(
            'background-color: rgb(113, 162, 188);\nfont: 12pt "Arial";')
        open_project_layout.addWidget(dialog.create_project_btn)

        return dialog

    def set_code_path(self):
        """为代码路径选择目录
        """
        current = self.preference_setting_dialog.code_root_path_le.text()
        if not current or not os.path.isdir(current):
            current = os.path.expanduser("~")
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self.preference_setting_dialog,
            "Choose the code directory",
            current,
            QtWidgets.QFileDialog.Option.ShowDirsOnly
        )
        if not path:
            return
        self.preference_setting_dialog.code_root_path_le.setText(path)

    def save_preference_info(self):
        if self.preference_setting_dialog.eng_rb.isChecked():
            language = "English"
        if self.preference_setting_dialog.ch_rb.isChecked():
            language = "Chinese"

        default_path = self.preference_setting_dialog.project_root_path_le.text()
        code_path = self.preference_setting_dialog.code_root_path_le.text()

        preference_info = {
            "Thumbnail size": self.preference_setting_dialog.thumbnail_size_le.text(),
            "Thumbnails qulity": self.preference_setting_dialog.thumbnail_quality_cb.currentText(),
            "language": language,
            "default path": default_path,
            "code path": code_path
        }
        with open(self.config_file_path, "w") as config_file:
            json.dump(preference_info, config_file, indent=4)

        # 保存后立即在主窗口生效
        if default_path and os.path.isdir(default_path):
            if default_path != self.parent.default_path:
                self.parent.default_path = default_path
                self.parent.populate_tree_view_ui()
        if code_path:
            self.parent.code_path = code_path
            self.parent.main_widget.code_panel.set_code_path(code_path)

    def init_preference_info(self):
        if not os.path.exists(self.config_file_path):
            return
        try:
            with open(self.config_file_path, 'r') as f:
                preference_info = json.load(f)
        except Exception:
            return
        self.preference_setting_dialog.thumbnail_size_le.setText(
            preference_info.get("Thumbnail size", ""))
        self.preference_setting_dialog.thumbnail_quality_cb.setCurrentText(
            preference_info.get("Thumbnails qulity", ""))
        self.preference_setting_dialog.project_root_path_le.setText(
            preference_info.get("default path", ""))
        self.preference_setting_dialog.code_root_path_le.setText(
            preference_info.get("code path", "")
            or os.path.join(self.parent.default_path, "code"))
        if preference_info.get("language") == "Chinese":
            self.preference_setting_dialog.ch_rb.setChecked(True)
        else:
            self.preference_setting_dialog.eng_rb.setChecked(True)

    def set_project_hierarchy_dialog(self):
        """in the page of preference dialog
        """
        self.level_wigets_list = []

        dialog = QtWidgets.QDialog(self)
        dialog.setObjectName("Dialog")
        dialog.setWindowTitle("Create project hierarchy")

        vertical_layout = QtWidgets.QVBoxLayout(dialog)
        vertical_layout.setContentsMargins(0, 0, 0, 0)
        vertical_layout.setSpacing(0)

        top_widget = QtWidgets.QWidget()
        top_widget.setObjectName("top_widget")
        level_top_layout = QtWidgets.QVBoxLayout(top_widget)
        level_top_layout.setContentsMargins(0, 0, 0, 0)
        level_top_layout.setSpacing(0)
        vertical_layout.addWidget(top_widget)

        header_layout = QtWidgets.QHBoxLayout()
        level_plus_btn = QtWidgets.QPushButton()
        level_plus_btn.setObjectName("level_plus_btn")
        header_layout.addWidget(level_plus_btn)
        header_layout.addItem(QtWidgets.QSpacerItem(
            383, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum))
        level_top_layout.addLayout(header_layout)

        level_1_grp = QtWidgets.QGroupBox()
        level_1_grp.setObjectName("level_1_grp")
        level_1_layout = QtWidgets.QVBoxLayout(level_1_grp)
        level_top_layout.addWidget(level_1_grp)

        label_row = QtWidgets.QHBoxLayout()
        level_1_label = QtWidgets.QLabel("level_1")
        level_1_label.setObjectName("label")
        firstlevel_plus_btn = QtWidgets.QPushButton()
        firstlevel_plus_btn.setObjectName("firstlevel_plus_btn")
        label_row.addWidget(level_1_label)
        label_row.addItem(QtWidgets.QSpacerItem(
            40, 20, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum))
        label_row.addWidget(firstlevel_plus_btn)
        level_1_layout.addLayout(label_row)

        first_level_le = QtWidgets.QLineEdit()
        first_level_le.setObjectName("first_level_le_1")
        first_level_le.setStyleSheet("border: 1px solid rgb(100,100,100);")
        level_1_layout.addWidget(first_level_le)

        level_top_layout.addItem(QtWidgets.QSpacerItem(
            20, 187, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding))

        dialog.top_widget = top_widget
        dialog.level_top_layout = level_top_layout
        dialog.level_plus_btn = level_plus_btn
        dialog.firstlevel_plus_btn = firstlevel_plus_btn
        dialog.level_1_layout = level_1_layout

        self.project_hierarchy_dialog = dialog

        dialog_btns = self.project_hierarchy_dialog.findChildren(QtWidgets.QPushButton)
        for btn in dialog_btns:
            self.parent.set_icon_to_button("add_level.png", btn)

        self.project_hierarchy_dialog.firstlevel_plus_btn.clicked.connect(
            partial(self.add_a_le_to_level,
                    self.project_hierarchy_dialog.level_1_layout)
        )
        self.project_hierarchy_dialog.level_plus_btn.clicked.connect(self.add_level_widget)
        self.project_hierarchy_dialog.setModal(QtCore.Qt.ApplicationModal)
        self.project_hierarchy_dialog.exec_()


def main():
    win = AssetLibrary_Win()
    win.show()
    return win


def reload():
    """热重载：关闭现有窗口、重新导入所有子模块，再打开新窗口。
    在 Maya 等 DCC 内修改代码后执行此函数即可生效，无需重启宿主进程。

    用法（Maya Script Editor）：
        import assetLibrary_app
        assetLibrary_app.reload()
    """
    import asset_lib_utils.utils as _utils
    import asset_lib_utils.flowlayout as _flow
    import asset_lib_utils.code_panel as _code
    import dcc_interface as _dcc
    import assetLibrary_app as _app

    # 关闭已有窗口
    app_instance = QtWidgets.QApplication.instance()
    if app_instance:
        for widget in app_instance.topLevelWidgets():
            if isinstance(widget, AssetLibrary_Win):
                widget.close()
                widget.deleteLater()

    # 按依赖顺序重新加载
    importlib.reload(_dcc)
    importlib.reload(_utils)
    importlib.reload(_flow)
    importlib.reload(_code)
    importlib.reload(_app)

    # 用重载后的模块重新打开窗口
    return _app.main()


if __name__ == "__main__":
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    main()
