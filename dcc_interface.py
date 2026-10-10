"""dcc_interface.py：DCC 适配层。

所有 DCC 专属 import 都集中在本文件，其余模块不得 import DCC。

对外接口（其余模块只依赖这 4 个函数）：
    get_main_window()  -> 可作 QMainWindow parent 的主窗口对象（Blender / standalone 返回 None）
    open_file(path)
    import_file(path)
    reference_file(path)
"""

import os
import importlib.util


def _has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def detect_dcc():
    """运行时检测当前 DCC 环境，返回 'maya' / 'max' / 'blender' / 'standalone'。"""
    if _has_module("maya"):
        return "maya"
    if _has_module("pymxs") or _has_module("qtmax"):
        return "max"
    if _has_module("bpy"):
        return "blender"
    return "standalone"


def _exec_py_in_main(path):
    """读取 .py 文件并在 __main__ 命名空间里 exec，等同于在脚本编辑器里运行。

    在 Maya / Blender / 独立运行下都适用；把 __file__ 设为脚本路径，
    便于脚本内用相对路径定位资源。
    """
    import __main__
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    globals_dict = __main__.__dict__
    globals_dict["__file__"] = path
    code = compile(source, path, "exec")
    exec(code, globals_dict)


# ---------------------------------------------------------------------------
# Maya
# ---------------------------------------------------------------------------
def _get_maya_main_window():
    try:
        import maya.OpenMayaUI as omui
        from shiboken2 import wrapInstance
        from PySide2 import QtWidgets
    except ImportError:
        import maya.OpenMayaUI as omui
        from shiboken6 import wrapInstance
        from PySide6 import QtWidgets
    ptr = omui.MQtUtil.mainWindow()
    return wrapInstance(int(ptr), QtWidgets.QMainWindow)


def _maya_open_file(path):
    import maya.cmds as cmds
    cmds.file(path, o=True, force=True)


def _maya_import_file(path):
    import maya.cmds as cmds
    cmds.file(path, i=True)


def _maya_reference_file(path):
    import maya.cmds as cmds
    cmds.file(path, r=True)


def _maya_set_project(path):
    import maya.cmds as cmds
    cmds.workspace(path, openWorkspace=True)


def _maya_run_script(path):
    # 在 Maya 的 __main__ 命名空间里执行，效果等同于脚本编辑器里跑
    _exec_py_in_main(path)


def _maya_capture_thumbnail(out_path, width, height):
    import maya.cmds as cmds
    cur = cmds.currentTime(query=True)
    cmds.playblast(
        frame=cur,
        format="image",
        completeFilename=out_path,
        width=width,
        height=height,
        showOrnaments=False,
        viewer=False,
        offScreen=True,
        percent=100,
        quality=100,
        forceOverwrite=True,
    )


# ---------------------------------------------------------------------------
# 3ds Max
# ---------------------------------------------------------------------------
def _get_max_main_window():
    from qtmax import GetQMaxMainWindow
    return GetQMaxMainWindow()


def _max_open_file(path):
    from pymxs import runtime as rt
    rt.loadMaxFile(path)


def _max_import_file(path):
    from pymxs import runtime as rt
    rt.mergeMaxFile(path)


def _max_reference_file(path):
    from pymxs import runtime as rt
    rt.xrefs.addNewXRefFile(path)


def _max_set_project(path):
    from pymxs import runtime as rt
    rt.pathConfig.setCurrentProjectFolder(path)


def _max_run_script(path):
    from pymxs import runtime as rt
    rt.python.ExecuteFile(path)


def _max_capture_thumbnail(out_path, width, height):
    from pymxs import runtime as rt
    bmp = rt.gw.getViewportDib()
    bmp.filename = out_path
    rt.save(bmp)
    rt.close(bmp)


# ---------------------------------------------------------------------------
# Blender（原生 bpy，无 Qt 主窗口）
# ---------------------------------------------------------------------------
def _get_blender_main_window():
    return None  # 原生面板不需要 parent


def _blender_open_file(path):
    import bpy
    bpy.ops.wm.open_mainfile(filepath=path)


def _blender_import_file(path):
    import bpy
    # 追加：directory 为库内以 / 结尾的路径，filename 为对象名
    directory = path + "/Object/"
    bpy.ops.wm.append(filepath=path, directory=directory)


def _blender_reference_file(path):
    import bpy
    directory = path + "/Object/"
    bpy.ops.wm.link(filepath=path, directory=directory)


def _blender_set_project(path):
    # Blender 无工程目录概念，此处不做处理
    pass


def _blender_run_script(path):
    _exec_py_in_main(path)


def _blender_capture_thumbnail(out_path, width, height):
    import bpy
    scene = bpy.context.scene
    render = scene.render
    prev_path = render.filepath
    prev_x = render.resolution_x
    prev_y = render.resolution_y
    prev_pct = render.resolution_percentage
    try:
        render.filepath = out_path
        render.resolution_x = width
        render.resolution_y = height
        render.resolution_percentage = 100
        # 视口 OpenGL 渲染，写出静帧
        bpy.ops.render.opengl(write_still=True)
    finally:
        render.filepath = prev_path
        render.resolution_x = prev_x
        render.resolution_y = prev_y
        render.resolution_percentage = prev_pct


# ---------------------------------------------------------------------------
# 统一分发
# ---------------------------------------------------------------------------
_DCC = detect_dcc()

_MAIN_WINDOW = {
    "maya": _get_maya_main_window,
    "max": _get_max_main_window,
    "blender": _get_blender_main_window,
}

_OPEN = {
    "maya": _maya_open_file,
    "max": _max_open_file,
    "blender": _blender_open_file,
}

_IMPORT = {
    "maya": _maya_import_file,
    "max": _max_import_file,
    "blender": _blender_import_file,
}

_REFERENCE = {
    "maya": _maya_reference_file,
    "max": _max_reference_file,
    "blender": _blender_reference_file,
}

_SET_PROJECT = {
    "maya": _maya_set_project,
    "max": _max_set_project,
    "blender": _blender_set_project,
}

_RUN_SCRIPT = {
    "maya": _maya_run_script,
    "max": _max_run_script,
    "blender": _blender_run_script,
}

_CAPTURE_THUMBNAIL = {
    "maya": _maya_capture_thumbnail,
    "max": _max_capture_thumbnail,
    "blender": _blender_capture_thumbnail,
}


def get_main_window():
    if _DCC == "standalone":
        return None  # 独立运行时窗口无 parent
    func = _MAIN_WINDOW.get(_DCC, _get_maya_main_window)
    return func()


def open_file(path):
    func = _OPEN.get(_DCC, _maya_open_file)
    func(path)


def import_file(path):
    func = _IMPORT.get(_DCC, _maya_import_file)
    func(path)


def reference_file(path):
    func = _REFERENCE.get(_DCC, _maya_reference_file)
    func(path)


def set_project(path):
    func = _SET_PROJECT.get(_DCC, _maya_set_project)
    func(path)


def run_script(path):
    """在当前 DCC 中运行 .py 脚本；standalone 下直接 exec。"""
    func = _RUN_SCRIPT.get(_DCC, _exec_py_in_main)
    func(path)


def can_capture_thumbnail():
    """当前环境是否支持从视口生成缩略图（standalone 不支持）。"""
    return _DCC in _CAPTURE_THUMBNAIL


def capture_thumbnail(out_path, width=256, height=256):
    """把当前 DCC 视口截图保存到 out_path（方案 C）。

    standalone 下不支持，抛出 RuntimeError。返回实际生成的文件路径。
    """
    func = _CAPTURE_THUMBNAIL.get(_DCC)
    if func is None:
        raise RuntimeError("Capturing a viewport thumbnail is not supported here.")
    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir)
    func(out_path, width, height)
    # 某些 DCC（如 Maya playblast）可能自动追加扩展名，这里做一次兜底查找
    if os.path.exists(out_path):
        return out_path
    stem, _ = os.path.splitext(out_path)
    for candidate in (stem + ".png", stem + ".0.png", stem + ".jpg"):
        if os.path.exists(candidate):
            return candidate
    return out_path
