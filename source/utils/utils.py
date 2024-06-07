import os, time, platform
import logging
from functools import partial

import maya.cmds as cmds
import maya.OpenMayaUI as omui
from shiboken2 import wrapInstance
from PySide2 import QtWidgets, QtCore, QtGui

DRIVE = "U:"
DEFAULT_PATH = "{DRIVE}/{PROJECT}/CG/Asset"

ASSET_DEFAULT_BUTTON_WIDTH = 50


def open_folder_of_given_path(dir_path: str):
    """Open the directory window

    Arguments:
        dir_path -- the directory path
    """
    if os.path.exists(dir_path):
        if platform.system() == "Windows":
            os.startfile(dir_path)

def resource_path(file_name: str):
    """to get the absolute path of file in source directory
    Arguments:
        file_name -- file name with suffix
    Returns:
        abs_file_path -> str: the absolute path of file in source directory
    """
    current_file_dir = os.path.dirname(__file__)
    abs_file_path = os.path.join(current_file_dir, "..", file_name)
    return abs_file_path


def get_maya_window_ptr():
    """to get maya window pointer in QMainWindow form

    Returns:
        maya window pointer in QMainWindow form
    """
    ptr = omui.MQtUtil.mainWindow()
    maya_win = wrapInstance(int(ptr), QtWidgets.QMainWindow)
    return maya_win


def find_files_in_path(path):
    """return all the files paths in given path"""
    dirs_files = os.listdir(path)
    files_path = []
    # get the files in the default path
    for d_r in dirs_files:
        dir_file_path = os.path.join(path, d_r)
        if not os.path.isdir(dir_file_path):
            files_path.append(dir_file_path)
    return files_path


def find_dirs_in_path(path):
    """return all the files paths in given path"""
    dirs_files = os.listdir(path)
    dirs_path = []
    # get the files in the default path
    for d_r in dirs_files:
        dir_file_path = os.path.join(path, d_r)
        if os.path.isdir(dir_file_path):
            dirs_path.append(dir_file_path)
    return dirs_path


def hum_convert(value):
    units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
    size = 1024
    for unit in units:
        if value/size < 1:
            return f"{value}{unit}"
        value = round(value/size,2)


def operation_maya_file(file_path, operation):
    if operation == "Open":
        cmds.file(file_path, o=True, force=True)
    elif operation == "Import":
        cmds.file(file_path, i=True)
    elif operation == "Reference":
        cmds.file(file_path, r=True)


def delete_file(file_path):
    if os.path.exists(file_path):
        os.remove(file_path)


def rename_file(file_path, new_name):
    if os.path.exists(file_path):
        name, suffix = os.path.basename(file_path).split(".")
        dir_name = os.path.dirname(file_path)
        new_name = f"{new_name}.{suffix}"
        new_path = os.path.join(dir_name, new_name)
        os.rename(file_path, new_path)


class MenuCustomStyle(QtWidgets.QProxyStyle):
    def __init__(self):
        super().__init__()

    def pixelMetric(self, metric, option, widget):
        if metric == QtWidgets.QStyle.PM_SmallIconSize:
            return 18
        return super().pixelMetric(metric, option, widget)


class AssetButtonGroup(object):
    def __init__(self) -> None:
        self.asset_buttons_list = None

    def add_button(self, button):
        if self.asset_buttons_list is None:
            self.asset_buttons_list = []
        self.asset_buttons_list.append(button)
        button.clicked.connect(partial(self.set_exclusive, button))
    
    def set_exclusive(self, clicked_button):
        for button in self.asset_buttons_list:
            if button == clicked_button:
                button.setCheck(True)
            else:
                button.setCheck(False)
    
    def set_selected(self, select):
        if select is None:
            for button in self.asset_buttons_list:
                button.setCheck(False)
            

class AssetButton(QtWidgets.QWidget):
    clicked = QtCore.Signal()
    tag_qss_stylesheet = """
            font: 75 9pt "Arial";
            color: rgb(0,0,0);
            background-color: rgba(255,255,255,255);
            border: 2px solid rgba(255,255,255,255);
        """
    menu_qss_stylesheet = """
        QMenu {
            background-color: rgba(0,0,0);
            color: rgb(160,160,160);
        }
        QMenu::item { padding: 10px; }
        QMenu::item:selected {
            color: white;
            }
        QMenu::separator{
            height: 1px;
            background-color: rgb(55,55,55);
        }
        """
    suffix_label_color = {
        "3dObject": "rgba(136,195,227);",
        "image": "rgba(255,255,255,255);",
        "video": "rgba(254,212,98,255);",
        "texture": "rgba(150,140,239,255);"
    }
        
    def __init__(self, name, image_path, parent=None):
        super(AssetButton, self).__init__(parent=parent)
        self.name = name
        self.image_path = image_path
        self.parent = parent
        self.asset_path = None
        self.asset_type = None
        self.isChecked = False
        self.set_custom_style()
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.create_menu)

    def set_custom_style(self):
        try:
            name, suffix = self.name.split(".")
        except:
            logging.error("the name of button should only have one '.'")
        self.setFixedWidth(120)
        suffix_type = self.get_suffix_categorized(suffix)
        if suffix_type:
            color = self.suffix_label_color[suffix_type]
            self.tag_qss_stylesheet = self.tag_qss_stylesheet.replace("rgba(255,255,255,255);", color)
        suffix = suffix.upper()
        self.main_layout = QtWidgets.QVBoxLayout(self)
        self.main_layout.setSpacing(0)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.tag_widget = QtWidgets.QFrame(self)
        tag_layout = QtWidgets.QHBoxLayout(self.tag_widget)
        tag_layout.setContentsMargins(0, 0, 0, 0)
        spacerItem = QtWidgets.QSpacerItem(0, 0, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
        tag_label = QtWidgets.QLabel(suffix)
        tag_label.setStyleSheet(self.tag_qss_stylesheet)
        tag_layout.addItem(spacerItem)
        tag_layout.addWidget(tag_label)

        self.icon_label = QtWidgets.QLabel()
        self.pixmap = QtGui.QPixmap(self.image_path)
        self.icon_label.setPixmap(self.pixmap)
        self.asset_widget = QtWidgets.QWidget(self)
        asset_layout = QtWidgets.QHBoxLayout(self.asset_widget)
        asset_layout.setContentsMargins(0, 0, 0, 0)
        self.asset_name_label = QtWidgets.QLabel(name)
        self.asset_name_label.setWordWrap(True)
        self.asset_name_label.setAlignment(QtCore.Qt.AlignCenter)
        self.asset_name_label.setStyleSheet("""
                background-color: rgba(255,255,255, 0);
            """)
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
        if suffix in object_format:
            self.asset_type = "3dObject"
        elif suffix in image_format:
            self.asset_type = "image"
        elif suffix in video_format:
            self.asset_type = "video"
        elif suffix in texture_format:
            self.asset_type = "texture"
        else:
            self.asset_type = None
        return self.asset_type
        
    def mousePressEvent(self, event: QtGui.QMouseEvent):
        self.clicked.emit()

    def isCheck(self):
        return self.isChecked

    def setCheck(self, isCheck):
        if isCheck:
            self.isChecked = True
            self.setStyleSheet("""
            background-color: rgba(0,0,0, 100);
            border: 10px solid rgba(82, 133, 166, 0);
        """)
        else:
            self.isChecked = False
            self.setStyleSheet("""
            background-color: rgba(0,0,0, 0);
            border: 10px solid rgba(82, 133, 166, 0);
        """)
            
    def set_path_to_clipboard(self):
        clipboard = QtWidgets.QApplication.clipboard()
        asset_dir = os.path.dirname(self.asset_path)
        clipboard.setText(asset_dir)

    def set_file_to_clipboard(self):
        clipboard = QtWidgets.QApplication.clipboard()
        mime_data = QtCore.QMimeData()
        url = QtCore.QUrl.fromLocalFile(self.asset_path)
        mime_data.setUrls([url])
        clipboard.setMimeData(mime_data)

    def delete_file(self):
        delete_file(self.asset_path)
        self.parent.populate_asset_in_display_widget()
    
    def rename_file(self):
        self.parent.get_input_dialog()
        new_name = self.parent.input_name
        rename_file(self.asset_path, new_name)
        self.parent.populate_asset_in_display_widget()

    def create_menu(self):
        menu_style = MenuCustomStyle()
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(AssetButton.menu_qss_stylesheet)
        menu.setStyle(menu_style)
        
        operation_img_path = "../icon/file_operation.png"
        abs_operation_img_path = resource_path(operation_img_path)
        sub_operation_menu = QtWidgets.QMenu()
        sub_operation_menu.setStyle(menu_style)
        sub_operation_menu.setIcon(QtGui.QIcon(abs_operation_img_path))
        sub_operation_menu.addAction("Open", partial(operation_maya_file, self.asset_path, "Open"))
        sub_operation_menu.addAction("Import", partial(operation_maya_file, self.asset_path, "Import"))
        sub_operation_menu.addAction("Reference", partial(operation_maya_file, self.asset_path, "Reference"))
        sub_operation_menu.addSeparator()
        asset_path_dir = os.path.dirname(self.asset_path)
        sub_operation_menu.addAction("Open in Explorer", partial(open_folder_of_given_path, asset_path_dir))
        sub_operation_menu.addAction("Copy Path", self.set_path_to_clipboard)
        sub_operation_menu.addSeparator()
        sub_operation_menu.addAction("Copy", self.set_file_to_clipboard)
        sub_operation_menu.addAction("Delete", self.delete_file)
        sub_operation_menu.addAction("Rename", self.rename_file)
        sub_operation_menu.addSeparator()
        sub_operation_menu.addAction("AddTags")
        sub_operation_menu.setStyleSheet(AssetButton.menu_qss_stylesheet)
        menu.addMenu(sub_operation_menu)
        # like action 
        like_action = QtWidgets.QAction()
        like_img_path = "../icon/like.png"
        abs_like_img_path = resource_path(like_img_path)
        like_action.setIcon(QtGui.QIcon(abs_like_img_path))
        menu.addAction(like_action)

        # write description action
        write_action = QtWidgets.QAction()
        write_img_path = "../icon/write.png"
        abs_write_img_path = resource_path(write_img_path)
        write_action.setIcon(QtGui.QIcon(abs_write_img_path))
        menu.addAction(write_action)
        
        menu.exec_(QtGui.QCursor.pos())

    def change_icon(self, is_image=False):
        pass
    
    def get_information(self):
        self.asset_path = os.path.normpath(self.asset_path)
        create_time = time.ctime(os.path.getctime(self.asset_path))
        modify_time = time.ctime(os.path.getmtime(self.asset_path))
        size = os.stat(self.asset_path).st_size
        format_size = hum_convert(size)
        asset_information_dic = {
            "Name": self.name,
            "Type": self.asset_type,
            "Created": create_time,
            "Modified": modify_time,
            "Size": format_size,
            "location": self.asset_path
        }
        return asset_information_dic
    
    def set_size(self, width):
        self.pixmap = self.pixmap.scaledToWidth(width)
        self.icon_label.setPixmap(self.pixmap)

