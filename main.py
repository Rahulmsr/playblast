
from __future__ import annotations

import os
import shutil
import subprocess
import uuid

from maya import OpenMayaUI, cmds

from . import APP_NAME, maya_capture, settings, tokens
from . import ffmpeg as ffmpeg_tools
from .qt_compat import QtCore, QtGui, QtWidgets, wrapInstance

WINDOW_OBJECT = "BlueprintPlayblastWindow"
_WINDOW = None


def maya_main_window():
    ptr = OpenMayaUI.MQtUtil.mainWindow()
    if ptr:
        return wrapInstance(int(ptr), QtWidgets.QWidget)
    return None


def show():
    global _WINDOW
    if _WINDOW is not None:
        try:
            _WINDOW.close()
            _WINDOW.deleteLater()
        except RuntimeError:
            pass
    _WINDOW = PlayblastWindow(parent=maya_main_window())
    _WINDOW.show()
    return _WINDOW


class PlayblastWindow(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data = settings.load_settings()
        self.setObjectName(WINDOW_OBJECT)
        self.setWindowTitle(APP_NAME)
        self.setMinimumWidth(430)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Window)

        self._build_ui()
        self._load_data()
        self._refresh_cameras()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget()
        self.playblast_tab = QtWidgets.QWidget()
        self.shot_mask_tab = QtWidgets.QWidget()
        self.settings_tab = QtWidgets.QWidget()
        self.tabs.addTab(self.playblast_tab, "Playblast")
        self.tabs.addTab(self.shot_mask_tab, "Shot Mask")
        self.tabs.addTab(self.settings_tab, "Settings")
        layout.addWidget(self.tabs)

        self._build_playblast_tab()
        self._build_shot_mask_tab()
        self._build_settings_tab()

        footer = QtWidgets.QHBoxLayout()
        self.shot_mask_btn = QtWidgets.QPushButton("Shot Mask")
        self.playblast_btn = QtWidgets.QPushButton("Playblast")
        self.menu_btn = QtWidgets.QPushButton("...")
        self.shot_mask_btn.clicked.connect(
            lambda: self.tabs.setCurrentWidget(self.shot_mask_tab)
        )
        self.playblast_btn.clicked.connect(self.run_playblast)
        self.menu_btn.clicked.connect(self._show_menu)
        footer.addWidget(self.shot_mask_btn)
        footer.addWidget(self.playblast_btn, 1)
        footer.addWidget(self.menu_btn)
        layout.addLayout(footer)

    def _build_playblast_tab(self):
        layout = QtWidgets.QVBoxLayout(self.playblast_tab)
        form = QtWidgets.QFormLayout()

        self.directory_edit = QtWidgets.QLineEdit()
        self.directory_btn = QtWidgets.QPushButton("...")
        directory_row = self._row(self.directory_edit, self.directory_btn)
        self.directory_btn.clicked.connect(
            lambda: self._browse_directory(self.directory_edit)
        )
        form.addRow("Directory", directory_row)

        self.filename_edit = QtWidgets.QLineEdit()
        self.force_overwrite_check = QtWidgets.QCheckBox("Force overwrite")
        form.addRow(
            "Filename", self._row(self.filename_edit, self.force_overwrite_check)
        )

        options = self._section("Options")
        option_form = QtWidgets.QFormLayout(options)
        self.camera_combo = QtWidgets.QComboBox()
        self.refresh_camera_btn = QtWidgets.QPushButton("Refresh")
        self.hide_defaults_check = QtWidgets.QCheckBox("Hide defaults")
        cam_row = self._row(
            self.camera_combo, self.refresh_camera_btn, self.hide_defaults_check
        )
        self.refresh_camera_btn.clicked.connect(self._refresh_cameras)
        option_form.addRow("Camera", cam_row)

        self.resolution_combo = QtWidgets.QComboBox()
        self.resolution_combo.addItems(list(maya_capture.RESOLUTION_PRESETS.keys()))
        self.width_spin = self._spin(1, 16384, 960)
        self.height_spin = self._spin(1, 16384, 540)
        self.resolution_combo.currentTextChanged.connect(self._apply_resolution_preset)
        option_form.addRow(
            "Resolution",
            self._row(
                self.resolution_combo,
                self.width_spin,
                QtWidgets.QLabel("x"),
                self.height_spin,
            ),
        )

        self.frame_range_combo = QtWidgets.QComboBox()
        self.frame_range_combo.addItems(["Playback", "Render", "Animation", "Selected", "Custom"])
        self.start_spin = self._spin(-100000, 100000, 1)
        self.end_spin = self._spin(-100000, 100000, 100)
        self.frame_range_combo.currentTextChanged.connect(self._refresh_frame_range_fields)
        option_form.addRow(
            "Frame Range",
            self._row(self.frame_range_combo, self.start_spin, self.end_spin),
        )

        self.step_combo = QtWidgets.QComboBox()
        self.step_combo.addItems(["1", "2", "3", "4", "5"])
        self.encoding_combo = QtWidgets.QComboBox()
        self.encoding_combo.addItems(["h264 mp4", "h264 mov", "png sequence"])
        option_form.addRow(
            "Every", self._row(self.step_combo, QtWidgets.QLabel("frame(s)"))
        )
        option_form.addRow("Encoding", self.encoding_combo)

        check_grid = QtWidgets.QGridLayout()
        self.ornaments_check = QtWidgets.QCheckBox("Ornaments")
        self.overscan_check = QtWidgets.QCheckBox("Overscan")
        self.shot_mask_check = QtWidgets.QCheckBox("Shot Mask")
        self.viewer_check = QtWidgets.QCheckBox("Show in Viewer")
        check_grid.addWidget(self.ornaments_check, 0, 0)
        check_grid.addWidget(self.overscan_check, 0, 1)
        check_grid.addWidget(self.shot_mask_check, 1, 0)
        check_grid.addWidget(self.viewer_check, 1, 1)
        option_form.addRow("", check_grid)

        self.log_edit = QtWidgets.QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMinimumHeight(120)
        self.log_to_script_check = QtWidgets.QCheckBox("Log to Script Editor")
        self.clear_log_btn = QtWidgets.QPushButton("Clear")
        self.clear_log_btn.clicked.connect(self.log_edit.clear)

        layout.addLayout(form)
        layout.addWidget(options)
        layout.addWidget(self._section("Logging", self.log_edit))
        layout.addLayout(self._row_layout(self.log_to_script_check, self.clear_log_btn))

    def _build_shot_mask_tab(self):
        layout = QtWidgets.QVBoxLayout(self.shot_mask_tab)
        form = QtWidgets.QFormLayout()
        self.scope_combo = QtWidgets.QComboBox()
        self.scope_combo.addItem("<All Cameras>")
        self.select_camera_btn = QtWidgets.QPushButton("Select...")
        form.addRow("Camera", self._row(self.scope_combo, self.select_camera_btn))
        layout.addLayout(form)

        labels_box = self._section("Labels")
        labels_form = QtWidgets.QFormLayout(labels_box)
        self.label_edits = {}
        for key, label in [
            ("top_left", "Top-Left"),
            ("top_center", "Top-Center"),
            ("top_right", "Top-Right"),
            ("bottom_left", "Bottom-Left"),
            ("bottom_center", "Bottom-Center"),
            ("bottom_right", "Bottom-Right"),
        ]:
            edit = QtWidgets.QLineEdit()
            button = QtWidgets.QPushButton("Insert")
            button.clicked.connect(
                lambda _=False, field=edit: self._insert_token(field)
            )
            self.label_edits[key] = edit
            labels_form.addRow(label, self._row(edit, button))
        layout.addWidget(labels_box)

        logo_box = self._section("Logo")
        logo_form = QtWidgets.QFormLayout(logo_box)
        self.use_logo_check = QtWidgets.QCheckBox("Use Logo")
        self.logo_edit = QtWidgets.QLineEdit()
        self.logo_btn = QtWidgets.QPushButton("...")
        self.logo_btn.clicked.connect(
            lambda: self._browse_file(
                self.logo_edit, "Images (*.png *.jpg *.jpeg *.tif *.tiff *.bmp)"
            )
        )
        self.logo_position_combo = QtWidgets.QComboBox()
        self.logo_position_combo.addItems(
            [
                "top_left",
                "top_center",
                "top_right",
                "bottom_left",
                "bottom_center",
                "bottom_right",
            ]
        )
        self.logo_vertical_combo = QtWidgets.QComboBox()
        self.logo_vertical_combo.addItems(["middle", "edge"])
        self.logo_width_spin = self._spin(1, 4000, 120)
        self.logo_alpha_spin = self._double_spin(0, 1, 1)
        logo_form.addRow("", self.use_logo_check)
        logo_form.addRow("Logo Path", self._row(self.logo_edit, self.logo_btn))
        logo_form.addRow("Position", self.logo_position_combo)
        logo_form.addRow("Vertical", self.logo_vertical_combo)
        logo_form.addRow(
            "Width",
            self._row(
                self.logo_width_spin, QtWidgets.QLabel("Alpha"), self.logo_alpha_spin
            ),
        )
        layout.addWidget(logo_box)

        counter_box = self._section("Counter")
        counter_form = QtWidgets.QFormLayout(counter_box)
        self.counter_padding_spin = self._spin(1, 12, 4)
        counter_form.addRow("Padding", self.counter_padding_spin)
        layout.addWidget(counter_box)
        layout.addStretch()

    def _build_settings_tab(self):
        layout = QtWidgets.QVBoxLayout(self.settings_tab)
        playblast_box = self._section("Playblast")
        form = QtWidgets.QFormLayout(playblast_box)
        self.ffmpeg_edit = QtWidgets.QLineEdit()
        self.ffmpeg_btn = QtWidgets.QPushButton("...")
        self.ffmpeg_btn.clicked.connect(
            lambda: self._browse_file(self.ffmpeg_edit, "ffmpeg (ffmpeg.exe ffmpeg)")
        )
        self.temp_dir_edit = QtWidgets.QLineEdit()
        self.temp_dir_btn = QtWidgets.QPushButton("...")
        self.temp_dir_btn.clicked.connect(
            lambda: self._browse_directory(self.temp_dir_edit)
        )
        self.player_edit = QtWidgets.QLineEdit()
        self.player_btn = QtWidgets.QPushButton("...")
        self.player_btn.clicked.connect(
            lambda: self._browse_file(
                self.player_edit,
                "Applications (*.exe);;All Files (*.*)",
            )
        )
        self.reset_playblast_btn = QtWidgets.QPushButton("Reset Playblast")
        self.reset_playblast_btn.clicked.connect(self._reset_playblast)
        form.addRow("ffmpeg Path", self._row(self.ffmpeg_edit, self.ffmpeg_btn))
        form.addRow("Temp Dir", self._row(self.temp_dir_edit, self.temp_dir_btn))
        form.addRow("Player Path", self._row(self.player_edit, self.player_btn))
        form.addRow("", self.reset_playblast_btn)
        layout.addWidget(playblast_box)

        text_box = self._section("Text")
        text_form = QtWidgets.QFormLayout(text_box)
        self.font_edit = QtWidgets.QLineEdit()
        self.font_btn = QtWidgets.QPushButton("Select...")
        self.font_btn.clicked.connect(self._browse_font)
        self.text_color_btn = ColorButton()
        self.text_alpha_spin = self._double_spin(0, 1, 1)
        self.text_scale_spin = self._double_spin(0.1, 5, 1)
        self.font_size_spin = self._spin(1, 300, 24)
        self.margin_spin = self._spin(0, 500, 24)
        text_form.addRow("Font", self._row(self.font_edit, self.font_btn))
        text_form.addRow("Font Size", self.font_size_spin)
        text_form.addRow(
            "Color",
            self._row(
                self.text_color_btn,
                QtWidgets.QLabel("Alpha"),
                self.text_alpha_spin,
                QtWidgets.QLabel("Scale"),
                self.text_scale_spin,
            ),
        )
        text_form.addRow("Margin", self.margin_spin)
        layout.addWidget(text_box)

        borders_box = self._section("Borders")
        borders_form = QtWidgets.QFormLayout(borders_box)
        self.top_bar_check = QtWidgets.QCheckBox("Top")
        self.bottom_bar_check = QtWidgets.QCheckBox("Bottom")
        self.bar_color_btn = ColorButton("#000000")
        self.bar_alpha_spin = self._double_spin(0, 1, 0.75)
        self.bar_height_spin = self._spin(0, 300, 48)
        borders_form.addRow(
            "Enabled", self._row(self.top_bar_check, self.bottom_bar_check)
        )
        borders_form.addRow(
            "Color",
            self._row(
                self.bar_color_btn, QtWidgets.QLabel("Alpha"), self.bar_alpha_spin
            ),
        )
        borders_form.addRow("Height", self.bar_height_spin)
        layout.addWidget(borders_box)

        self.reset_mask_btn = QtWidgets.QPushButton("Reset Shot Mask")
        self.reset_mask_btn.clicked.connect(self._reset_shot_mask)
        mask_box = self._section("Shot Mask")
        mask_form = QtWidgets.QFormLayout(mask_box)
        mask_form.addRow("", self.reset_mask_btn)
        layout.addWidget(mask_box)
        layout.addStretch()

    def _load_data(self):
        playblast = self.data["playblast"]
        shot_mask = self.data["shot_mask"]
        general = self.data["settings"]

        directory = playblast["directory"]
        if maya_capture.is_legacy_project_directory(directory):
            directory = "{scene_dir}"
            playblast["directory"] = directory
        self.directory_edit.setText(directory)
        self.filename_edit.setText(playblast["filename"])
        self.force_overwrite_check.setChecked(playblast["force_overwrite"])
        self.hide_defaults_check.setChecked(playblast["hide_default_cameras"])
        resolution_name = self._resolution_preset_for_size(
            playblast.get("width"), playblast.get("height")
        )
        if playblast.get("resolution_preset") == "Custom":
            resolution_name = "Custom"
        self.resolution_combo.setCurrentText(resolution_name)
        self.width_spin.setValue(playblast["width"])
        self.height_spin.setValue(playblast["height"])
        self.frame_range_combo.setCurrentText(playblast["frame_range"])
        self.start_spin.setValue(playblast["start_frame"])
        self.end_spin.setValue(playblast["end_frame"])
        self._refresh_frame_range_fields(self.frame_range_combo.currentText())
        self.step_combo.setCurrentText(str(playblast.get("step", 1)))
        self.encoding_combo.setCurrentText(playblast["encoding"])
        self.ornaments_check.setChecked(playblast["show_ornaments"])
        self.overscan_check.setChecked(playblast["overscan"])
        self.shot_mask_check.setChecked(playblast["shot_mask"])
        self.viewer_check.setChecked(playblast["show_in_viewer"])
        self.log_to_script_check.setChecked(playblast["log_to_script_editor"])

        for key, edit in self.label_edits.items():
            edit.setText(shot_mask["labels"].get(key, ""))
        self.font_edit.setText(shot_mask["font_path"])
        self.font_size_spin.setValue(shot_mask["font_size"])
        self.text_color_btn.set_color(shot_mask["text_color"])
        self.text_alpha_spin.setValue(shot_mask["text_alpha"])
        self.text_scale_spin.setValue(shot_mask["text_scale"])
        self.margin_spin.setValue(shot_mask["margin"])
        self.top_bar_check.setChecked(shot_mask["top_bar"])
        self.bottom_bar_check.setChecked(shot_mask["bottom_bar"])
        self.bar_color_btn.set_color(shot_mask["bar_color"])
        self.bar_alpha_spin.setValue(shot_mask["bar_alpha"])
        self.bar_height_spin.setValue(shot_mask["bar_height"])
        self.counter_padding_spin.setValue(shot_mask["counter_padding"])
        self.logo_edit.setText(shot_mask["logo_path"])
        self.use_logo_check.setChecked(shot_mask.get("use_logo", True))
        self.logo_position_combo.setCurrentText(shot_mask["logo_position"])
        self.logo_vertical_combo.setCurrentText(
            shot_mask.get("logo_vertical_align", "middle")
        )
        self.logo_width_spin.setValue(shot_mask["logo_width"])
        self.logo_alpha_spin.setValue(shot_mask["logo_alpha"])

        self.ffmpeg_edit.setText(general["ffmpeg_path"])
        self.temp_dir_edit.setText(general["temp_dir"])
        self.player_edit.setText(general.get("player_path", ""))

    def _collect_data(self, save=True):
        playblast = self.data["playblast"]
        shot_mask = self.data["shot_mask"]
        general = self.data["settings"]

        playblast.update(
            {
                "directory": self.directory_edit.text(),
                "filename": self.filename_edit.text(),
                "force_overwrite": self.force_overwrite_check.isChecked(),
                "camera": self.camera_combo.currentText(),
                "hide_default_cameras": self.hide_defaults_check.isChecked(),
                "resolution_preset": self._resolution_preset_for_size(
                    self.width_spin.value(), self.height_spin.value()
                ),
                "width": self.width_spin.value(),
                "height": self.height_spin.value(),
                "frame_range": self.frame_range_combo.currentText(),
                "start_frame": self.start_spin.value(),
                "end_frame": self.end_spin.value(),
                "step": int(self.step_combo.currentText()),
                "encoding": self.encoding_combo.currentText(),
                "show_ornaments": self.ornaments_check.isChecked(),
                "overscan": self.overscan_check.isChecked(),
                "shot_mask": self.shot_mask_check.isChecked(),
                "show_in_viewer": self.viewer_check.isChecked(),
                "log_to_script_editor": self.log_to_script_check.isChecked(),
            }
        )
        shot_mask.update(
            {
                "camera_scope": self.scope_combo.currentText(),
                "font_path": self.font_edit.text(),
                "font_size": self.font_size_spin.value(),
                "text_color": self.text_color_btn.color_name(),
                "text_alpha": self.text_alpha_spin.value(),
                "text_scale": self.text_scale_spin.value(),
                "margin": self.margin_spin.value(),
                "top_bar": self.top_bar_check.isChecked(),
                "bottom_bar": self.bottom_bar_check.isChecked(),
                "bar_color": self.bar_color_btn.color_name(),
                "bar_alpha": self.bar_alpha_spin.value(),
                "bar_height": self.bar_height_spin.value(),
                "counter_padding": self.counter_padding_spin.value(),
                "use_logo": self.use_logo_check.isChecked(),
                "logo_path": self.logo_edit.text(),
                "logo_position": self.logo_position_combo.currentText(),
                "logo_vertical_align": self.logo_vertical_combo.currentText(),
                "logo_width": self.logo_width_spin.value(),
                "logo_alpha": self.logo_alpha_spin.value(),
            }
        )
        for key, edit in self.label_edits.items():
            shot_mask["labels"][key] = edit.text()
        general["ffmpeg_path"] = self.ffmpeg_edit.text()
        general["temp_dir"] = self.temp_dir_edit.text()
        general["player_path"] = self.player_edit.text()
        if save:
            return settings.save_settings(self.data)
        return ""

    def run_playblast(self):
        self._collect_data()
        playblast = self.data["playblast"]
        shot_mask = self.data["shot_mask"]
        general = self.data["settings"]
        camera = playblast.get("camera") or maya_capture.active_camera()
        run_temp_dir = ""

        try:
            temp_root = tokens.expand(general["temp_dir"], camera=camera)
            run_temp_dir = os.path.join(temp_root, uuid.uuid4().hex)
            output = maya_capture.output_path(playblast, camera=camera)
            sequence, start, end = maya_capture.capture_sequence(
                playblast, run_temp_dir, self.log
            )
            audio_clip = maya_capture.timeline_audio_clip(start, end)
            if audio_clip:
                self.log(
                    "Timeline audio: {0} (trim {1:.3f}s, delay {2:.3f}s)".format(
                        audio_clip.get("node", ""),
                        audio_clip.get("trim_start", 0.0),
                        audio_clip.get("delay", 0.0),
                    )
                )
            if playblast.get("shot_mask", True) or "h264" in playblast.get(
                "encoding", ""
            ):
                output = ffmpeg_tools.encode_sequence(
                    general["ffmpeg_path"],
                    sequence,
                    output,
                    start,
                    playblast,
                    shot_mask if playblast.get("shot_mask", True) else {"labels": {}},
                    camera,
                    self.log,
                    audio_clip,
                )
            self.log("Finished: {0}".format(output))
            if playblast.get("show_in_viewer") and os.path.exists(output):
                self._open_movie(output)
        except Exception as exc:
            self.log("ERROR: {0}".format(exc))
            cmds.warning(str(exc))
        finally:
            if run_temp_dir and os.path.isdir(run_temp_dir):
                shutil.rmtree(run_temp_dir, ignore_errors=True)

    def _open_movie(self, output):
        player_path = tokens.expand(self.data["settings"].get("player_path", ""))
        if player_path:
            if not os.path.exists(player_path):
                raise RuntimeError("Player executable was not found: {0}".format(player_path))
            subprocess.Popen([player_path, output])
            self.log("Opened movie in player: {0}".format(player_path))
            return

        try:
            os.startfile(output)
        except AttributeError:
            cmds.launch(view=True, movie=output)
        self.log("Opened movie with system player.")

    def log(self, message):
        text = str(message)
        self.log_edit.appendPlainText(text)
        if self.log_to_script_check.isChecked():
            print("[Blueprint Playblast] " + text)

    def _refresh_cameras(self):
        current = self.camera_combo.currentText()
        self.camera_combo.clear()
        cams = maya_capture.cameras(
            include_defaults=not self.hide_defaults_check.isChecked()
        )
        active = maya_capture.active_camera()
        if active and active not in cams:
            cams.insert(0, active)
        self.camera_combo.addItems(cams)
        if current:
            self.camera_combo.setCurrentText(current)
        self.scope_combo.clear()
        self.scope_combo.addItem("<All Cameras>")
        self.scope_combo.addItems(cams)


    def _refresh_frame_range_fields(self, mode=None):
        mode = mode or self.frame_range_combo.currentText()
        is_custom = str(mode or "").lower() == "custom"
        self.start_spin.setEnabled(is_custom)
        self.end_spin.setEnabled(is_custom)
        if is_custom:
            return
        try:
            start, end = maya_capture.frame_range(
                mode, self.start_spin.value(), self.end_spin.value()
            )
        except Exception as exc:
            self.log("Could not read {0} frame range: {1}".format(mode, exc))
            return
        self.start_spin.setValue(start)
        self.end_spin.setValue(end)

    def _apply_resolution_preset(self, name):
        value = maya_capture.RESOLUTION_PRESETS.get(name)
        if value:
            self.width_spin.setValue(value[0])
            self.height_spin.setValue(value[1])

    def _resolution_preset_for_size(self, width, height):
        size = (int(width or 0), int(height or 0))
        for name, preset_size in maya_capture.RESOLUTION_PRESETS.items():
            if preset_size == size:
                return name
        return "Custom"

    def _insert_token(self, field):
        menu = QtWidgets.QMenu(self)
        tokens_list = [
            ("Scene Name", "{scene}"),
            ("Scene Directory", "{scene_dir}"),
            ("Frame Count", "{counter}"),
            ("Frame Number", "{frame}"),
            ("Camera Name", "{camera}"),
            ("Focal Length", "{focal_length}"),
            ("User Name", "{user}"),
            ("Date", "{date}"),
            ("Time", "{time}"),
            ("New Line", "\\n"),
            ("Project", "{project}"),
        ]
        for label, token in tokens_list:
            action = menu.addAction(label)
            action.triggered.connect(lambda _=False, value=token: field.insert(value))
        menu.exec_(QtGui.QCursor.pos())

    def _show_menu(self):
        menu = QtWidgets.QMenu(self)
        menu.addAction("Save Settings", lambda: self._collect_data())
        menu.addAction("Clear User Overrides", self._clear_user_overrides)
        if settings.is_admin_mode():
            menu.addAction("Save Studio Defaults", self._save_studio_settings)
        menu.addAction("Create Shelf Button", self._create_shelf)
        menu.exec_(QtGui.QCursor.pos())

    def _save_studio_settings(self):
        self._collect_data(save=False)
        path = settings.save_studio_settings(self.data)
        self.log("Studio defaults saved: {0}".format(path))

    def _create_shelf(self):
        from .shelf import create_shelf_button

        create_shelf_button()
        self.log("Shelf button created.")

    def _clear_user_overrides(self):
        path = settings.clear_user_settings()
        self.data = settings.load_settings()
        self._load_data()
        self._refresh_cameras()
        self.log("User overrides cleared: {0}".format(path))

    def _reset_playblast(self):
        self._collect_data(save=False)
        settings.reset_playblast(self.data)
        self._load_data()
        settings.save_settings(self.data)

    def _reset_shot_mask(self):
        self._collect_data(save=False)
        settings.reset_shot_mask(self.data)
        self._load_data()
        settings.save_settings(self.data)

    def _browse_directory(self, field):
        result = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Directory", tokens.expand(field.text())
        )
        if result:
            field.setText(os.path.normpath(result))

    def _browse_file(self, field, file_filter):
        result, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select File", "", file_filter
        )
        if result:
            field.setText(os.path.normpath(result))

    def _browse_font(self):
        self._browse_file(self.font_edit, "Fonts (*.ttf *.otf *.ttc)")

    def _section(self, title, child=None):
        box = QtWidgets.QGroupBox(title)
        if child is not None:
            layout = QtWidgets.QVBoxLayout(box)
            layout.addWidget(child)
        return box

    def _row(self, *widgets):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        for item in widgets:
            layout.addWidget(item)
        return widget

    def _row_layout(self, *widgets):
        layout = QtWidgets.QHBoxLayout()
        for item in widgets:
            layout.addWidget(item)
        return layout

    def _spin(self, minimum, maximum, value):
        spin = QtWidgets.QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        return spin

    def _double_spin(self, minimum, maximum, value):
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(3)
        spin.setSingleStep(0.05)
        spin.setValue(value)
        return spin


class ColorButton(QtWidgets.QPushButton):
    def __init__(self, color="#FFFFFF", parent=None):
        super().__init__(parent)
        self._color = QtGui.QColor(color)
        self.clicked.connect(self.pick_color)
        self.setFixedWidth(72)
        self._refresh()

    def set_color(self, color):
        self._color = QtGui.QColor(color)
        self._refresh()

    def color_name(self):
        return self._color.name().upper()

    def pick_color(self):
        color = QtWidgets.QColorDialog.getColor(self._color, self)
        if color.isValid():
            self._color = color
            self._refresh()

    def _refresh(self):
        self.setText(self.color_name())
        self.setStyleSheet(
            "QPushButton { background: %s; color: %s; }"
            % (self.color_name(), self._text_color())
        )

    def _text_color(self):
        lightness = self._color.lightness()
        return "#000000" if lightness > 128 else "#FFFFFF"
