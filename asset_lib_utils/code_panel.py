"""asset_lib_utils/code_panel.py：代码界面（浏览 / 新建 / 重命名 / 删除 / 编辑 .py 文件）。

本模块不 import 任何 DCC 模块，纯 Qt 实现，Maya / 3ds Max / 独立运行均可用。

对外提供两个类：
    CodePanelWidget  -- 嵌在主窗口中的代码文件面板（列表 + 右键菜单）
    CodeEditorDialog -- 双击文件弹出的代码编辑窗口（可改名、复制粘贴、保存）
"""

import os
import re
import shutil

try:
    from PySide2 import QtWidgets, QtCore, QtGui
except ImportError:
    from PySide6 import QtWidgets, QtCore, QtGui

import asset_lib_utils.utils as utils


PY_TEMPLATE = "# -*- coding: utf-8 -*-\n\n"


def exec_dialog(dialog):
    """PySide2 / PySide6 通用的模态执行（两者对 exec_ 的支持不一致）。"""
    func = getattr(dialog, "exec_", None)
    if func is None:
        func = getattr(dialog, "exec", None)
    return func()


class PythonHighlighter(QtGui.QSyntaxHighlighter):
    """极简 Python 语法高亮（用 python re，避免 Qt 正则版本差异）。"""

    def __init__(self, document):
        super(PythonHighlighter, self).__init__(document)
        self.rules = []

        keyword_fmt = QtGui.QTextCharFormat()
        keyword_fmt.setForeground(QtGui.QColor(86, 156, 214))
        keyword_fmt.setFontWeight(QtGui.QFont.Bold)
        keywords = [
            "def", "class", "return", "import", "from", "as", "if", "elif",
            "else", "for", "while", "break", "continue", "pass", "try",
            "except", "finally", "raise", "with", "lambda", "yield", "global",
            "not", "and", "or", "in", "is", "None", "True", "False", "self",
        ]
        self.rules.append((re.compile(r"\b(" + "|".join(keywords) + r")\b"), keyword_fmt))

        string_fmt = QtGui.QTextCharFormat()
        string_fmt.setForeground(QtGui.QColor(206, 145, 120))
        self.rules.append((re.compile(r"(\"[^\"\n]*\"|'[^'\n]*')"), string_fmt))

        comment_fmt = QtGui.QTextCharFormat()
        comment_fmt.setForeground(QtGui.QColor(106, 153, 85))
        self.rules.append((re.compile(r"#[^\n]*"), comment_fmt))

        number_fmt = QtGui.QTextCharFormat()
        number_fmt.setForeground(QtGui.QColor(181, 206, 168))
        self.rules.append((re.compile(r"\b\d+\b"), number_fmt))

    def highlightBlock(self, text):
        for pattern, fmt in self.rules:
            for match in pattern.finditer(text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)


class CodePanelWidget(QtWidgets.QWidget):
    """代码文件面板：展示代码根目录下的所有 .py 文件。"""

    def __init__(self, parent=None):
        super(CodePanelWidget, self).__init__(parent=parent)
        self.main_win = parent
        self.py_icon = QtGui.QIcon()
        self.setObjectName("code_panel_widget")
        self._build_ui()
        self._set_icons()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ---- top bar ----
        top_widget = QtWidgets.QWidget()
        top_widget.setObjectName("code_top_widget")
        top_layout = QtWidgets.QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 20, 6)
        top_layout.setSpacing(6)

        self.path_le = QtWidgets.QLineEdit()
        self.path_le.setObjectName("code_path_le")
        self.path_le.setReadOnly(True)
        self.path_le.setMinimumHeight(25)
        self.path_le.setStyleSheet(
            'border: 1px solid rgba(255,255,255,50);\n'
            'background-color: rgba(0, 0, 0, 50);\n'
            'font: 10pt "Arial";'
        )
        self.path_le.setPlaceholderText("Code directory is not set")

        self.browse_btn = QtWidgets.QPushButton()
        self.browse_btn.setObjectName("code_browse_btn")
        self.browse_btn.setToolTip("Choose the code directory")
        self.refresh_btn = QtWidgets.QPushButton()
        self.refresh_btn.setObjectName("code_refresh_btn")
        self.refresh_btn.setToolTip("Refresh")
        self.add_btn = QtWidgets.QPushButton()
        self.add_btn.setObjectName("code_add_btn")
        self.add_btn.setToolTip("New python file")
        self.delete_btn = QtWidgets.QPushButton()
        self.delete_btn.setObjectName("code_delete_btn")
        self.delete_btn.setToolTip("Delete the selected python file")

        top_layout.addWidget(self.path_le)
        top_layout.addWidget(self.browse_btn)
        top_layout.addWidget(self.refresh_btn)
        top_layout.addWidget(self.add_btn)
        top_layout.addWidget(self.delete_btn)

        layout.addWidget(top_widget)

        # ---- file list ----
        self.file_list = QtWidgets.QListWidget()
        self.file_list.setObjectName("code_file_list")
        self.file_list.setSpacing(2)
        self.file_list.setStyleSheet(
            'QListWidget{font: 11pt "Arial";\n'
            'border: 1px solid rgba(255,255,255,50);\n'
            'background-color: rgba(0, 0, 0, 40);}\n'
            'QListWidget::item{padding: 4px;}\n'
            'QListWidget::item:selected{background-color: rgba(82, 133, 166, 150);}'
        )
        self.file_list.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self.show_menu)
        self.file_list.itemDoubleClicked.connect(self.open_editor)

        layout.addWidget(self.file_list, 1)

        # ---- signals ----
        self.browse_btn.clicked.connect(self.choose_code_path)
        self.refresh_btn.clicked.connect(self.refresh)
        self.add_btn.clicked.connect(self.add_py_file)
        self.delete_btn.clicked.connect(self.delete_py_file)

    def _set_icons(self):
        if not self.main_win:
            return
        set_icon = getattr(self.main_win, "set_icon_to_button", None)
        if not set_icon:
            return
        set_icon("root_path.png", self.browse_btn)
        set_icon("asset_update.png", self.refresh_btn)
        set_icon("add_asset.png", self.add_btn)
        set_icon("delete_directory.png", self.delete_btn)
        icon_path = utils.resource_path("icon/write.png")
        if os.path.exists(icon_path):
            self.py_icon = QtGui.QIcon(icon_path)
        else:
            self.py_icon = QtGui.QIcon()

    # --------------------------------------------------------------- path
    def code_dir(self):
        return self.path_le.text()

    def set_code_path(self, path):
        self.path_le.setText(path if path else "")
        self.refresh()

    def choose_code_path(self):
        current = self.code_dir() or os.path.expanduser("~")
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Choose the code directory",
            current,
            QtWidgets.QFileDialog.Option.ShowDirsOnly
        )
        if not path:
            return
        self.set_code_path(path)
        if self.main_win is not None:
            self.main_win.code_path = path

    def ensure_code_dir(self):
        """确保代码目录存在，不存在则创建；返回是否可用。"""
        path = self.code_dir()
        if not path:
            QtWidgets.QMessageBox.warning(
                self, "Code Path", "Please choose a code directory first.")
            return False
        if not os.path.isdir(path):
            try:
                os.makedirs(path)
            except Exception as err:
                QtWidgets.QMessageBox.warning(
                    self, "Code Path", "Can not create the directory:\n{}".format(err))
                return False
        return True

    def refresh(self):
        self.file_list.clear()
        path = self.code_dir()
        if not path or not os.path.isdir(path):
            place_holder = QtWidgets.QListWidgetItem("Code directory is not available")
            place_holder.setFlags(QtCore.Qt.NoItemFlags)
            self.file_list.addItem(place_holder)
            return

        py_files = []
        for root, dirs, files in os.walk(path):
            dirs[:] = sorted([d for d in dirs if d != "__pycache__"])
            for name in sorted(files):
                if not name.endswith(".py"):
                    continue
                full_path = os.path.join(root, name)
                py_files.append(full_path)

        for full_path in py_files:
            rel_path = os.path.relpath(full_path, path).replace("\\", "/")
            item = QtWidgets.QListWidgetItem(self.py_icon, rel_path)
            item.setData(QtCore.Qt.UserRole, full_path)
            item.setToolTip(full_path)
            self.file_list.addItem(item)

        if not py_files:
            place_holder = QtWidgets.QListWidgetItem(
                "No .py file yet, right click to create one")
            place_holder.setFlags(QtCore.Qt.NoItemFlags)
            self.file_list.addItem(place_holder)

    def filter_files(self, text):
        """根据搜索栏输入过滤列表（大小写不敏感）。"""
        keyword = (text or "").strip().lower()
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if not (item.flags() & QtCore.Qt.ItemIsEnabled):
                item.setHidden(bool(keyword))
                continue
            item.setHidden(bool(keyword) and keyword not in item.text().lower())

    # --------------------------------------------------------- operations
    def current_file_path(self):
        item = self.file_list.currentItem()
        if item is None:
            return None
        return item.data(QtCore.Qt.UserRole)

    def add_py_file(self):
        """新建一个 .py 文件并打开编辑窗口。"""
        if not self.ensure_code_dir():
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self, "New Python File", "Please enter the file name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if not name.endswith(".py"):
            name += ".py"
        file_path = os.path.join(self.code_dir(), name)
        if os.path.exists(file_path):
            QtWidgets.QMessageBox.warning(
                self, "Input Error", "{} already exists.".format(name))
            return
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(PY_TEMPLATE)
        except Exception as err:
            QtWidgets.QMessageBox.warning(
                self, "Error", "Can not create the file:\n{}".format(err))
            return
        self.refresh()
        self._select_file(file_path)
        self.open_editor()

    def delete_py_file(self):
        file_path = self.current_file_path()
        if not file_path:
            QtWidgets.QMessageBox.warning(
                self, "Delete", "Please select a python file first.")
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            "Delete",
            "Are you sure to delete:\n{}".format(file_path),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return
        try:
            os.remove(file_path)
        except Exception as err:
            QtWidgets.QMessageBox.warning(
                self, "Error", "Can not delete the file:\n{}".format(err))
        self.refresh()

    def rename_py_file(self):
        file_path = self.current_file_path()
        if not file_path:
            return
        old_name = os.path.basename(file_path)
        new_name, ok = QtWidgets.QInputDialog.getText(
            self, "Rename", "Please enter the new name:", text=old_name)
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()
        if not new_name.endswith(".py"):
            new_name += ".py"
        new_path = os.path.join(os.path.dirname(file_path), new_name)
        if os.path.abspath(new_path) == os.path.abspath(file_path):
            return
        if os.path.exists(new_path):
            QtWidgets.QMessageBox.warning(
                self, "Rename", "{} already exists.".format(new_name))
            return
        try:
            os.rename(file_path, new_path)
        except Exception as err:
            QtWidgets.QMessageBox.warning(
                self, "Error", "Can not rename the file:\n{}".format(err))
        self.refresh()
        self._select_file(new_path)

    def duplicate_py_file(self):
        """复制一份副本（原文件保持不变）。"""
        file_path = self.current_file_path()
        if not file_path:
            return
        base_name = os.path.basename(file_path)
        stem, _ = os.path.splitext(base_name)
        new_path = os.path.join(os.path.dirname(file_path), "{}_copy.py".format(stem))
        index = 1
        while os.path.exists(new_path):
            new_path = os.path.join(
                os.path.dirname(file_path), "{}_copy{}.py".format(stem, index))
            index += 1
        shutil.copy2(file_path, new_path)
        self.refresh()
        self._select_file(new_path)

    def copy_file_to_clipboard(self):
        file_path = self.current_file_path()
        if not file_path:
            return
        mime_data = QtCore.QMimeData()
        mime_data.setUrls([QtCore.QUrl.fromLocalFile(file_path)])
        QtWidgets.QApplication.clipboard().setMimeData(mime_data)

    def copy_path_to_clipboard(self):
        file_path = self.current_file_path()
        if not file_path:
            return
        QtWidgets.QApplication.clipboard().setText(file_path)

    def paste_files(self):
        """把剪贴板里的文件粘贴到代码目录。"""
        if not self.ensure_code_dir():
            return
        mime_data = QtWidgets.QApplication.clipboard().mimeData()
        if not mime_data.hasUrls():
            QtWidgets.QMessageBox.information(
                self, "Paste", "There is no file in the clipboard.")
            return
        target_dir = self.code_dir()
        for url in mime_data.urls():
            src = url.toLocalFile()
            if not os.path.isfile(src):
                continue
            dst = os.path.join(target_dir, os.path.basename(src))
            stem, suffix = os.path.splitext(os.path.basename(src))
            index = 1
            while os.path.exists(dst):
                dst = os.path.join(target_dir, "{}_{}{}".format(stem, index, suffix))
                index += 1
            try:
                shutil.copy2(src, dst)
            except Exception as err:
                QtWidgets.QMessageBox.warning(
                    self, "Error", "Can not paste {}:\n{}".format(src, err))
        self.refresh()

    def open_in_explorer(self):
        file_path = self.current_file_path()
        if file_path:
            utils.open_folder_of_given_path(os.path.dirname(file_path))
        elif self.code_dir():
            utils.open_folder_of_given_path(self.code_dir())

    def run_in_dcc(self):
        """在当前 DCC 中运行选中的 .py 脚本"""
        file_path = self.current_file_path()
        if not file_path or not os.path.exists(file_path):
            QtWidgets.QMessageBox.warning(
                self, "Run", "Please select a python file first.")
            return
        import dcc_interface
        try:
            dcc_interface.run_script(file_path)
        except Exception as err:
            QtWidgets.QMessageBox.warning(
                self, "Run", "Failed to run the script:\n{}".format(err))

    def add_code_dir_to_favorites(self):
        """把当前代码目录收藏到左下角的 Code 分类
        """
        if self.main_win is None:
            return
        add_favorite = getattr(self.main_win, "add_favorite", None)
        if add_favorite is None:
            return
        add_favorite("Code")

    def _select_file(self, file_path):
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.data(QtCore.Qt.UserRole) == file_path:
                self.file_list.setCurrentItem(item)
                return

    # ------------------------------------------------------------ editor
    def open_editor(self, item=None):
        file_path = self.current_file_path()
        if not file_path or not os.path.exists(file_path):
            return
        dialog = CodeEditorDialog(file_path, self)
        exec_dialog(dialog)
        self.refresh()

    # -------------------------------------------------------------- menu
    def show_menu(self, pos):
        item = self.file_list.itemAt(pos)
        # 右键不会自动改变选中项，这里手动同步，保证菜单作用在右键的那个文件上
        if item is not None and item.data(QtCore.Qt.UserRole):
            self.file_list.setCurrentItem(item)
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(utils.AssetButton.menu_qss_stylesheet)
        menu.setStyle(utils.MenuCustomStyle())

        menu.addAction("New Python File", self.add_py_file)
        menu.addAction("Add to Favorites", self.add_code_dir_to_favorites)
        menu.addAction("Paste", self.paste_files)
        menu.addSeparator()

        if item is not None and item.data(QtCore.Qt.UserRole):
            menu.addAction("Run in DCC", self.run_in_dcc)
            menu.addSeparator()
            menu.addAction("Open", self.open_editor)
            menu.addAction("Rename", self.rename_py_file)
            menu.addAction("Duplicate", self.duplicate_py_file)
            menu.addAction("Delete", self.delete_py_file)
            menu.addSeparator()
            menu.addAction("Copy", self.copy_file_to_clipboard)
            menu.addAction("Copy Path", self.copy_path_to_clipboard)
            menu.addSeparator()
            menu.addAction("Open in Explorer", self.open_in_explorer)

        menu.addAction("Refresh", self.refresh)
        menu.exec_(QtGui.QCursor.pos())


class CodeEditorDialog(QtWidgets.QDialog):
    """代码编辑窗口：可改名、编辑、保存（Ctrl+S），支持复制粘贴。"""

    def __init__(self, file_path, parent=None):
        super(CodeEditorDialog, self).__init__(parent=parent)
        self.file_path = os.path.normpath(file_path) if file_path else ""
        self.is_dirty = False
        self.setObjectName("CodeEditorDialog")
        self.setWindowTitle("Code Editor")
        self.resize(760, 560)
        self._build_ui()
        self._load_file()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ---- name row ----
        name_widget = QtWidgets.QWidget()
        name_layout = QtWidgets.QHBoxLayout(name_widget)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(6)

        name_label = QtWidgets.QLabel("Name:")
        name_label.setMinimumWidth(45)
        self.name_le = QtWidgets.QLineEdit()
        self.name_le.setObjectName("code_name_le")
        self.name_le.setMinimumHeight(24)
        self.name_le.setToolTip("Change the name and save to rename the file")
        name_layout.addWidget(name_label)
        name_layout.addWidget(self.name_le)

        self.path_label = QtWidgets.QLabel("")
        self.path_label.setStyleSheet("color: rgb(140,140,140);")
        name_layout.addWidget(self.path_label)
        layout.addWidget(name_widget)

        # ---- editor ----
        self.text_edit = QtWidgets.QPlainTextEdit()
        self.text_edit.setObjectName("code_text_edit")
        self.text_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        font = QtGui.QFont("Consolas", 11)
        font.setStyleHint(QtGui.QFont.Monospace)
        self.text_edit.setFont(font)
        self.text_edit.setStyleSheet(
            "QPlainTextEdit{background-color: rgb(30, 30, 30);\n"
            "color: rgb(220, 220, 220);\n"
            "selection-background-color: rgb(82, 133, 166);}"
        )
        try:
            self.text_edit.setTabStopWidth(32)
        except Exception:
            self.text_edit.setTabStopDistance(32)
        self.text_edit.textChanged.connect(self._mark_dirty)
        PythonHighlighter(self.text_edit.document())
        layout.addWidget(self.text_edit, 1)

        # ---- buttons ----
        button_box = QtWidgets.QDialogButtonBox()
        button_box.setObjectName("code_editor_bb")
        self.save_btn = button_box.addButton("Save", QtWidgets.QDialogButtonBox.AcceptRole)
        self.save_as_btn = button_box.addButton("Save As", QtWidgets.QDialogButtonBox.ActionRole)
        self.reload_btn = button_box.addButton("Reload", QtWidgets.QDialogButtonBox.ActionRole)
        close_btn = button_box.addButton("Close", QtWidgets.QDialogButtonBox.RejectRole)
        layout.addWidget(button_box)

        self.save_btn.clicked.connect(self.save_file)
        self.save_as_btn.clicked.connect(self.save_as_file)
        self.reload_btn.clicked.connect(self._load_file)
        close_btn.clicked.connect(self.reject)

        save_shortcut = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+S"), self)
        save_shortcut.activated.connect(self.save_file)

    # ------------------------------------------------------------ content
    def _mark_dirty(self):
        self.is_dirty = True

    def _load_file(self):
        self.path_label.setText(os.path.dirname(self.file_path))
        self.name_le.setText(os.path.basename(self.file_path))
        content = ""
        if self.file_path and os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                try:
                    with open(self.file_path, "r") as f:
                        content = f.read()
                except Exception as err:
                    QtWidgets.QMessageBox.warning(
                        self, "Error", "Can not read the file:\n{}".format(err))
        self.text_edit.setPlainText(content)
        self.is_dirty = False

    def _write_file(self, file_path):
        dir_name = os.path.dirname(file_path)
        if dir_name and not os.path.isdir(dir_name):
            os.makedirs(dir_name)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(self.text_edit.toPlainText())

    def save_file(self):
        """保存；若名称被修改则同时完成重命名。"""
        name = self.name_le.text().strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Input Error", "The name can not be empty.")
            return False
        if not name.endswith(".py"):
            name += ".py"

        new_path = os.path.normpath(os.path.join(os.path.dirname(self.file_path), name))
        old_path = os.path.normpath(self.file_path)

        if new_path != old_path:
            if os.path.exists(new_path):
                answer = QtWidgets.QMessageBox.question(
                    self,
                    "Save",
                    "{} already exists, overwrite it?".format(name),
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                    QtWidgets.QMessageBox.No
                )
                if answer != QtWidgets.QMessageBox.Yes:
                    return False
            if os.path.exists(old_path):
                try:
                    os.rename(old_path, new_path)
                except Exception as err:
                    QtWidgets.QMessageBox.warning(
                        self, "Error", "Can not rename the file:\n{}".format(err))
                    return False
            self.file_path = new_path

        try:
            self._write_file(self.file_path)
        except Exception as err:
            QtWidgets.QMessageBox.warning(
                self, "Error", "Can not save the file:\n{}".format(err))
            return False

        self.is_dirty = False
        self.path_label.setText(os.path.dirname(self.file_path))
        self.name_le.setText(os.path.basename(self.file_path))
        return True

    def save_as_file(self):
        default_path = self.file_path or os.path.join(os.path.expanduser("~"), "untitled.py")
        new_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Save As", default_path, "Python Files (*.py)")
        if not new_path:
            return
        if not new_path.endswith(".py"):
            new_path += ".py"
        try:
            self._write_file(new_path)
        except Exception as err:
            QtWidgets.QMessageBox.warning(
                self, "Error", "Can not save the file:\n{}".format(err))
            return
        self.file_path = os.path.normpath(new_path)
        self.name_le.setText(os.path.basename(self.file_path))
        self.path_label.setText(os.path.dirname(self.file_path))
        self.is_dirty = False

    def closeEvent(self, event):
        if self.is_dirty:
            answer = QtWidgets.QMessageBox.question(
                self,
                "Code Editor",
                "The file has been changed, save it?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
                | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Yes
            )
            if answer == QtWidgets.QMessageBox.Cancel:
                event.ignore()
                return
            if answer == QtWidgets.QMessageBox.Yes:
                if not self.save_file():
                    event.ignore()
                    return
        super(CodeEditorDialog, self).closeEvent(event)
