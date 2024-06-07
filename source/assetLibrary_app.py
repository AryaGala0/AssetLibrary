import os, shutil, json
from functools import partial

from PySide2 import QtWidgets, QtCore, QtGui
from PySide2.QtUiTools import QUiLoader

import utils.utils as utils
import utils.flowlayout as flow_layout


from pprint import pprint
from imp import reload
reload(utils)


LOADER = QUiLoader()


class AssetLibrary_Win(QtWidgets.QMainWindow):
    def __init__(self, parent=utils.get_maya_window_ptr()):
        super(AssetLibrary_Win, self).__init__(parent=parent)

        self.window_width = 1300
        self.window_height = 960
        self.directory_dialog = None
        self.permission_dialog = None
        self.preference_setting_dialog = None
        self.assets_layout = None
        self.info_widget = None
        self.asset_icon_size = 60

        self.default_path = "D:/Arya/test/assetlibrary_list"
        self.asset_depth = {
            "level_nums": 1,
            "is_each_folder": True,
            "aims_directories_list": None
            }

        # initial UI
        self.initUI()

    def initUI(self):
        """build user interface
        """
        self.setWindowTitle("AssetLibrary")
        self.setMinimumSize(self.window_width, self.window_height)
        # get the .ui file into qt loader
        ui_path = "../UI/main_window.ui"
        abs_ui_path = utils.resource_path(ui_path)
        if os.path.exists(abs_ui_path):
            ui_path = abs_ui_path
        ui_file = QtCore.QFile(ui_path)
        ui_file.open(QtCore.QFile.ReadOnly)
        self.main_widget = LOADER.load(ui_file, self)
        ui_file.close()
        self.main_widget.setWindowFlags(QtCore.Qt.Widget)
        self.setCentralWidget(self.main_widget)

        # add icon to buttons
        main_widget_btns = self.main_widget.findChildren(QtWidgets.QPushButton)
        for btn in main_widget_btns:
            icon_name = btn.objectName().replace("_btn", ".png")
            self.set_icon_to_button(icon_name, btn)
        
        # info widget
        self.populate_information_widget()
        info_dic = {
            "DRIVE": utils.DRIVE,
            "PROJECT": "EggyWawa"
        }
        # self.default_path = utils.DEFAULT_PATH.format_map(info_dic)
        # toolbar
        self.main_widget.actionSettings.triggered.connect(self.show_preference_setting_dialog)
        self.set_icon_to_button("setting.png", self.main_widget.actionSettings)
        
        # root path
        self.main_widget.root_path_le.setReadOnly(True)
        self.main_widget.root_path_btn.clicked.connect(self.set_root_path)
   
        # tree view 
        self.populate_tree_view_ui()
        self.main_widget.directory_treeview.doubleClicked.connect(self.populate_tree_view_ui)

        self.main_widget.directory_update_btn.clicked.connect(self.populate_tree_view_ui)
        self.main_widget.directory_back_btn.clicked.connect(self.back_to_last_directory)
        self.main_widget.add_directory_btn.clicked.connect(partial(self.get_permission_password_dialog, "add"))
        self.main_widget.delete_directory_btn.clicked.connect(partial(self.get_permission_password_dialog, "delete"))

        # asset widget
        self.main_widget.add_asset_btn.clicked.connect(self.add_asset)

        self.main_widget.asset_status_le.setReadOnly(True)

        self.show()
        self.populate_asset_in_display_widget()

    def set_icon_to_button(self, icon_name, button=None):
        """set icon to the button

        Arguments:
            icon_name -- icon file name in icon directory
            button -- the button you want to set icon to
        """
        icon_dir_path = "../icon"
        abs_icon_dir_path = utils.resource_path(icon_dir_path)
        if os.path.exists(abs_icon_dir_path):
            icon_dir_path = abs_icon_dir_path
        icon_path = os.path.join(icon_dir_path, icon_name)
        if not os.path.exists(icon_path):
            return
        try:
            button.setStyleSheet("background-color: rgba(255, 255, 255, 0);\nborder: 0px;")
        except:
            pass
        if not os.path.exists(icon_path):
            return
        try:
            icon = QtGui.QIcon(icon_path)
            button.setIcon(icon)
        except:
            pass

        return icon_path
    
    def get_all_directory_files(self, path, i):
        """get file in the i depth directory in path

        Arguments:
            path -- the top directory
            i -- the depth of directory you want to get file
        """
        if i == 0:
            files_path = utils.find_files_in_path(path)
            for file_path in files_path:
                if len(file_path.split(".")) == 2:
                    self.asset_files_path.append(file_path)
        else:
            dirs = utils.find_dirs_in_path(path)
            for _dir in dirs:
                new_path = os.path.join(path, _dir)
                self.get_all_directory_files(new_path, i-1)

    def get_files_in_specific_directory(self, path, dir_list, i):
        dirs = utils.find_dirs_in_path(path)
        for _dir in dirs:
            new_path = os.path.join(path, _dir)
            for sub_dir in dir_list:
                new_path = os.path.join(new_path, sub_dir)
            if os.path.exists(new_path):
                files_path = utils.find_files_in_path(new_path)
                for file_path in files_path:
                    if len(file_path.split(".")) == 2:
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

        # if the there are asset buttons in the layout,delete it and then
        # add them
        if self.assets_layout:
            self.main_widget.display_widget.deleteLater()
            self.main_widget.display_widget = QtWidgets.QWidget()
            self.main_widget.display_widget.setObjectName("display_widget")
            self.main_widget.sa_layout.addWidget(self.main_widget.display_widget)
        # add the assets button to the layout
        self.asset_btns = []
        self.assets_layout = flow_layout.FlowLayout(self.main_widget.display_widget)
        for ffile in self.asset_files_path:
            default_asset_btn_img_path = "../icon/object.png"
            abs_default_asset_btn_img_path = utils.resource_path(default_asset_btn_img_path)
            name = os.path.basename(ffile)
            file_btn = utils.AssetButton(name, abs_default_asset_btn_img_path, self)
            name, suffix = name.split(".")
            file_btn.asset_path = ffile
            if not file_btn.get_suffix_categorized(suffix):
                continue
            file_btn.set_size(self.asset_icon_size)
            self.assets_layout.addWidget(file_btn)
            self.AssetGroup.add_button(file_btn)
            file_btn.clicked.connect(partial(self.populate_information_widget, True))
            self.asset_btns.append(file_btn)

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
            production_spacer_item = QtWidgets.QSpacerItem(0, 0, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
            production_control_layout.addItem(production_spacer_item)
            
            # asset properties
            asset_properties_layout = QtWidgets.QVBoxLayout()
            asset_properties_title = QtWidgets.QLabel("ASSET PROPERTIES")
            asset_properties_layout.addWidget(asset_properties_title)
            asset_proper_spacer_item = QtWidgets.QSpacerItem(0, 0, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
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
        info_spacer_item1 = QtWidgets.QSpacerItem(0, 0, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)
        info_layout.addItem(info_spacer_item1)
        info_layout.addWidget(info_text_label)
        info_layout.addWidget(info_icon_label)   
        info_spacer_item2 = QtWidgets.QSpacerItem(0, 0, QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Expanding)   
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
        spacerItem = QtWidgets.QSpacerItem(0, 0, QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)
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
        self.default_path = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            dir=current_path,
            options=QtWidgets.QFileDialog.Option.ShowDirsOnly
        )
        self.populate_tree_view_ui()

    def back_to_last_directory(self):
        new_path = "/".join(self.default_path.split("/")[:-1])
        self.default_path = new_path
        self.populate_tree_view_ui()

    def get_input_dialog(self):
        ui_path = "../UI/get_input_name_dialog.ui"
        abs_ui_path = utils.resource_path(ui_path)
        if os.path.exists(abs_ui_path):
            ui_path = abs_ui_path
        ui_file = QtCore.QFile(ui_path)
        ui_file.open(QtCore.QFile.ReadOnly)
        self.input_dialog = LOADER.load(ui_file, self)
        ui_file.close()
        self.input_dialog.setWindowTitle("Add Directory")
        self.input_dialog.setModal(QtCore.Qt.ApplicationModal)
        self.input_dialog.accepted.connect(
            self.get_input_name
            )
        self.input_dialog.exec_()

    def get_input_name(self):
        if self.input_dialog:
            self.input_name = self.input_dialog.dir_name_le.text()
            
    def get_permission_password_dialog(self, to_deal_with):
        ui_path = "../UI/permission_password_dialog.ui"
        abs_ui_path = utils.resource_path(ui_path)
        if os.path.exists(abs_ui_path):
            ui_path = abs_ui_path
        ui_file = QtCore.QFile(ui_path)
        ui_file.open(QtCore.QFile.ReadOnly)
        self.permission_dialog = LOADER.load(ui_file, self)
        ui_file.close()
        self.permission_dialog.setWindowTitle("Permission password")
        self.permission_dialog.setModal(QtCore.Qt.ApplicationModal)

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
        except:
            shutil.rmtree(remove_path)

    def add_asset(self):
        pass
    

class Preference_Dialog(QtWidgets.QMainWindow):
    config_file_path = utils.resource_path("../config/preference_config.json")
    
    def __init__(self, parent):
        super().__init__(parent=parent)
        self.parent = parent
        self.init_ui()

    def init_ui(self):
        # get .ui file and add icon
        ui_path = "../UI/setting_dialog.ui"
        abs_ui_path = utils.resource_path(ui_path)
        if os.path.exists(abs_ui_path):
            ui_path = abs_ui_path
        ui_file = QtCore.QFile(ui_path)
        ui_file.open(QtCore.QFile.ReadOnly)
        self.preference_setting_dialog = LOADER.load(ui_file, self)
        ui_file.close()
        self.preference_setting_dialog.setWindowTitle("Preference Settings")
        preference_widget_btns = self.preference_setting_dialog.findChildren(QtWidgets.QPushButton) + self.preference_setting_dialog.findChildren(QtWidgets.QRadioButton)
        for btn in preference_widget_btns:
            icon_name = btn.objectName().replace("_btn", ".png")
            self.parent.set_icon_to_button(icon_name, btn)
        
        # preference setting tab
        self.preference_setting_dialog.preference_save_btn.clicked.connect(self.save_preference_info)
        # create project tab
        self.preference_setting_dialog.add_project_type_btn.clicked.connect(self.set_project_hierarchy_dialog)
        self.preference_setting_dialog.setModal(QtCore.Qt.ApplicationModal)
        self.preference_setting_dialog.exec_()

    def save_preference_info(self):
        if self.preference_setting_dialog.eng_rb.isChecked():
            language = "English"
        if self.preference_setting_dialog.ch_rb.isChecked():
            language = "Chinese"

        preference_info = {
            "Thumbnail size": self.preference_setting_dialog.thumbnail_size_le.text(),
            "Thumbnails qulity": self.preference_setting_dialog.thumbnail_quality_cb.currentText(),
            "language": language,
            "default path": self.preference_setting_dialog.project_root_path_le.text()
        }
        json_str = json.dumps(preference_info)
        config_file = open(self.config_file_path, "w")
        config_file.write(json_str)
        config_file.close()

    def init_preference_info(self):
        with open(self.config_file_path, 'r') as f:
            preference_info = json.load(f)
        f.close()
        self.preference_setting_dialog.thumbnail_size_le.setText(preference_info['Thumbnail size'])
        self.preference_setting_dialog.thumbnail_quality_cb.setCurrentText(preference_info['Thumbnails qulity'])



    def set_project_hierarchy_dialog(self):
        """in the page of preference dialog
        """
        self.level_wigets_list = []
        ui_path = "../UI/level_create_window.ui"
        abs_ui_path = utils.resource_path(ui_path)
        if os.path.exists(abs_ui_path):
            ui_path = abs_ui_path
        ui_file = QtCore.QFile(ui_path)
        ui_file.open(QtCore.QFile.ReadOnly)
        self.project_hierarchy_dialog = LOADER.load(ui_file, self)
        ui_file.close()
        dialog_btns = self.project_hierarchy_dialog.findChildren(QtWidgets.QPushButton)
        icon_name = "add_level.png"
        for btn in dialog_btns:
            self.parent.set_icon_to_button(icon_name, btn)
        self.project_hierarchy_dialog.setWindowTitle("Create project hierarchy")
        self.project_hierarchy_dialog.firstlevel_plus_btn.clicked.connect(
            partial(self.add_a_le_to_level,
                    self.project_hierarchy_dialog.level_1_layout)
                    )
        self.project_hierarchy_dialog.level_plus_btn.clicked.connect(self.add_level_widget)
        self.project_hierarchy_dialog.setModal(QtCore.Qt.ApplicationModal)
        self.project_hierarchy_dialog.exec_()


def main():
    win = AssetLibrary_Win()
    # win.show()
    # print(win.main_widget.display_widget.size())
    # for btn in win.asset_btns:
    #     print(btn.size())
