"""
Batch subtitle translation management dialog for Online Subtitle Translator.
Allows queuing multiple SRT files or scanning folders with customizable target languages
and real-time multi-account failover resilience.
"""

from __future__ import annotations
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QTableWidget,
    QTableWidgetItem, QFileDialog, QHeaderView, QMessageBox, QLabel,
    QWidget, QProgressBar, QFrame, QComboBox, QPlainTextEdit
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCursor

from app.core.config import (
    VERIFIED_TRANSLATION_PROVIDERS,
    SUPPORTED_TARGET_LANGUAGES,
    get_app_icon
)
from app.services.batch_service import BatchService, BatchTranslationItem
from app.workers.batch_worker import TranslationBatchWorker


class BatchDialog(QDialog):
    """Queue management dialog for multi-subtitle batch translation."""

    def __init__(self, batch_service: BatchService, parent=None):
        super().__init__(parent)
        self.batch_service = batch_service
        self.worker: Optional[TranslationBatchWorker] = None
        self._current_processing_name: Optional[str] = None

        self.setWindowTitle("Online Subtitle Translator — Batch Subtitle Queue")
        self.resize(880, 680)
        app_icon = get_app_icon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)

        self._build_ui()
        self._refresh_table()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)

        # Header description
        header = QLabel(
            "Batch Translate Subtitles: Add individual .srt files or entire folders.\n"
            "All jobs execute sequentially with automatic rate-limit failover across your configured accounts."
        )
        header.setStyleSheet("color: #94a3b8; font-size: 12px;")
        main_layout.addWidget(header)

        # Top Button Toolbar
        btn_bar = QHBoxLayout()
        self.btn_add_files = QPushButton("Add SRT Files...")
        self.btn_add_files.setObjectName("btn_secondary")
        self.btn_add_files.clicked.connect(self._add_srt_files)
        btn_bar.addWidget(self.btn_add_files)

        self.btn_add_folder = QPushButton("Add Folder...")
        self.btn_add_folder.setObjectName("btn_secondary")
        self.btn_add_folder.clicked.connect(self._add_srt_folder)
        btn_bar.addWidget(self.btn_add_folder)

        self.btn_remove = QPushButton("Remove Selected")
        self.btn_remove.setObjectName("btn_danger")
        self.btn_remove.clicked.connect(self._remove_selected)
        btn_bar.addWidget(self.btn_remove)

        self.btn_clear = QPushButton("Clear All")
        self.btn_clear.setObjectName("btn_danger")
        self.btn_clear.clicked.connect(self._clear_queue)
        btn_bar.addWidget(self.btn_clear)

        btn_bar.addStretch()
        self.lbl_queue_count = QLabel("Queue: 0 items")
        self.lbl_queue_count.setStyleSheet("font-weight: bold; color: #38bdf8;")
        btn_bar.addWidget(self.lbl_queue_count)
        main_layout.addLayout(btn_bar)

        # Table of Queued Subtitles
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "#", "Subtitle File Name", "Cues", "Target Language", "Status"
        ])
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        main_layout.addWidget(self.table)

        # Rate Limit Countdown Banner
        self.rate_limit_frame = QFrame()
        self.rate_limit_frame.setStyleSheet("""
            QFrame {
                background-color: #422006;
                border: 1px solid #f59e0b;
                border-radius: 6px;
                padding: 6px;
            }
        """)
        rl_layout = QHBoxLayout(self.rate_limit_frame)
        self.lbl_rl_icon = QLabel("⏳")
        self.lbl_rl_message = QLabel("Rate limit reached. Auto-switching / waiting...")
        self.lbl_rl_message.setStyleSheet("color: #fbbf24; font-weight: bold; font-size: 12px;")
        rl_layout.addWidget(self.lbl_rl_icon)
        rl_layout.addWidget(self.lbl_rl_message, 1)
        self.rate_limit_frame.hide()
        main_layout.addWidget(self.rate_limit_frame)

        # Controls & Settings Row
        ctrl_box = QHBoxLayout()

        ctrl_box.addWidget(QLabel("Target Language:"))
        self.combo_target_lang = QComboBox()
        for lang in SUPPORTED_TARGET_LANGUAGES:
            self.combo_target_lang.addItem(lang["name"], lang["code"])
        self.combo_target_lang.currentIndexChanged.connect(self._on_target_lang_changed)
        ctrl_box.addWidget(self.combo_target_lang)

        ctrl_box.addSpacing(16)
        ctrl_box.addWidget(QLabel("Provider & Model:"))
        self.combo_model = QComboBox()
        for p in VERIFIED_TRANSLATION_PROVIDERS:
            self.combo_model.addItem(f"{p.display_name} - {p.model_display_name}", (p.provider_id, p.model_id))
        ctrl_box.addWidget(self.combo_model, 1)

        main_layout.addLayout(ctrl_box)

        # Progress and Action Bar
        bottom_bar = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        bottom_bar.addWidget(self.progress_bar, 1)

        self.btn_start = QPushButton("Start Batch Translation")
        self.btn_start.setObjectName("btn_success")
        self.btn_start.setStyleSheet("padding: 8px 16px; font-weight: bold;")
        self.btn_start.clicked.connect(self._start_batch)
        bottom_bar.addWidget(self.btn_start)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("btn_danger")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_batch)
        bottom_bar.addWidget(self.btn_cancel)

        main_layout.addLayout(bottom_bar)

        # Current File Live Log Box (cleared per file)
        self.lbl_file_log_title = QLabel("📄 Current File Live Progress:")
        self.lbl_file_log_title.setStyleSheet("font-weight: 600; font-size: 12px; color: #94a3b8;")
        main_layout.addWidget(self.lbl_file_log_title)

        self.txt_file_log = QPlainTextEdit()
        self.txt_file_log.setReadOnly(True)
        self.txt_file_log.setFixedHeight(130)
        self.txt_file_log.setPlaceholderText("Live progress logs for the currently translating subtitle will appear here...")
        self.txt_file_log.setStyleSheet(
            "QPlainTextEdit {"
            "  background-color: #0f172a;"
            "  color: #e2e8f0;"
            "  border: 1px solid #334155;"
            "  border-radius: 6px;"
            "  font-family: Consolas, 'Segoe UI Mono', monospace;"
            "  font-size: 11px;"
            "  padding: 6px;"
            "}"
        )
        main_layout.addWidget(self.txt_file_log)

    def _on_target_lang_changed(self):
        target_code = self.combo_target_lang.currentData()
        for item in self.batch_service.translation_queue:
            item.target_language = target_code
        self._refresh_table()

    def _refresh_table(self):
        self.table.setRowCount(0)
        queue = self.batch_service.translation_queue
        self.lbl_queue_count.setText(f"Queue: {len(queue)} items")

        for row, item in enumerate(queue):
            self.table.insertRow(row)

            # 0: Index
            idx_item = QTableWidgetItem(str(row + 1))
            idx_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 0, idx_item)

            # 1: Name
            name_item = QTableWidgetItem(item.name)
            name_item.setToolTip(str(item.srt_path))
            self.table.setItem(row, 1, name_item)

            # 2: Cues count
            cues_item = QTableWidgetItem(str(item.cues_count) if item.cues_count > 0 else "-")
            cues_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 2, cues_item)

            # 3: Target Language
            lang_code = getattr(item, "target_language", "fa")
            lang_item = QTableWidgetItem(lang_code.upper())
            lang_item.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(row, 3, lang_item)

            # 4: Status
            status_item = QTableWidgetItem(item.status.value)
            status_item.setTextAlignment(Qt.AlignCenter)
            if item.status.value == "COMPLETED":
                status_item.setForeground(QColor("#22c55e"))
            elif item.status.value == "FAILED":
                status_item.setForeground(QColor("#ef4444"))
                if item.error_msg:
                    status_item.setToolTip(item.error_msg)
            elif item.status.value == "TRANSLATING":
                status_item.setForeground(QColor("#38bdf8"))
            self.table.setItem(row, 4, status_item)

    def _add_srt_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Subtitle Files",
            "",
            "SRT Subtitle Files (*.srt)"
        )
        if not files:
            return

        target_lang = self.combo_target_lang.currentData()
        for f in files:
            item = BatchTranslationItem(srt_path=f, target_language=target_lang)
            try:
                from app.core.srt_parser import SRTParser
                sub = SRTParser.parse_file(Path(f))
                item.cues_count = len(sub.cues)
            except Exception:
                pass
            self.batch_service.add_translation_item(item)

        self._refresh_table()

    def _add_srt_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder Containing Subtitles")
        if not folder:
            return

        target_lang = self.combo_target_lang.currentData()
        items = self.batch_service.scan_srt_folder(folder, target_language=target_lang)
        if not items:
            QMessageBox.information(self, "No Subtitles", f"No untranslated SRT files found in:\n{folder}")
            return

        for item in items:
            self.batch_service.add_translation_item(item)

        self._refresh_table()
        QMessageBox.information(self, "Added", f"Added {len(items)} subtitle file(s) from directory.")

    def _remove_selected(self):
        selected_rows = sorted(set(idx.row() for idx in self.table.selectedIndexes()), reverse=True)
        for r in selected_rows:
            if 0 <= r < len(self.batch_service.translation_queue):
                del self.batch_service.translation_queue[r]
        self._refresh_table()

    def _clear_queue(self):
        self.batch_service.clear()
        self._refresh_table()

    def _start_batch(self):
        if not self.batch_service.translation_queue:
            QMessageBox.warning(self, "Empty Queue", "Please add at least one subtitle file to the queue.")
            return

        provider_id, model_id = self.combo_model.currentData()
        target_lang = self.combo_target_lang.currentData()

        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_add_files.setEnabled(False)
        self.btn_add_folder.setEnabled(False)
        self.btn_remove.setEnabled(False)
        self.btn_clear.setEnabled(False)
        self.progress_bar.setValue(0)
        self._current_processing_name = None
        self.txt_file_log.clear()

        self.worker = TranslationBatchWorker(
            batch_service=self.batch_service,
            translation_provider=provider_id,
            translation_model=model_id,
            target_language=target_lang
        )
        self.worker.item_updated.connect(self._on_item_updated)
        self.worker.rate_limit_wait.connect(self._on_rate_limit)
        self.worker.rate_limit_cleared.connect(self._on_rate_limit_cleared)
        self.worker.batch_finished.connect(self._on_batch_finished)
        self.worker.failed.connect(self._on_batch_error)
        self.worker.log_emitted.connect(self._on_log_message)
        self.worker.start()

    def _on_log_message(self, line: str):
        self.txt_file_log.appendPlainText(line)
        self.txt_file_log.moveCursor(QTextCursor.End)

    def _on_item_updated(self, name: str, idx: int, total: int, status: str, pct: int):
        self._refresh_table()
        self.progress_bar.setValue(max(0, min(100, pct)))

        if status == "TRANSLATING":
            if self._current_processing_name != name:
                self._current_processing_name = name
                # Clean textbox for the new file (strictly non-cumulative)
                self.txt_file_log.clear()
                time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.txt_file_log.appendPlainText(f"[{time_str}] Started translating ({idx}/{total}): {name}")
                self.txt_file_log.moveCursor(QTextCursor.End)
        elif status == "COMPLETED" and self._current_processing_name == name:
            time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.txt_file_log.appendPlainText(f"[{time_str}] [100%] Subtitle translation completed for: {name}")
            self.txt_file_log.moveCursor(QTextCursor.End)

    def _on_rate_limit(self, provider: str, remaining_sec: int, attempt: int, reason: str):
        self.rate_limit_frame.show()
        self.lbl_rl_message.setText(
            f"Rate Limit ({provider}) — Attempt #{attempt}: Auto-rotating / waiting {remaining_sec}s..."
        )

    def _on_rate_limit_cleared(self, provider: str):
        self.rate_limit_frame.hide()

    def _on_batch_finished(self, success_count: int, failed_count: int, cancelled_count: int = 0):
        self.progress_bar.setValue(100)
        self._reset_ui_state()
        self._refresh_table()

        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.txt_file_log.appendPlainText(
            f"[{time_str}] Batch Translation Completed! Successful: {success_count}, Failed: {failed_count}"
        )
        self.txt_file_log.moveCursor(QTextCursor.End)

        msg = f"Batch Translation Finished!\n\nSuccessfully Translated: {success_count}\nFailed: {failed_count}"
        if cancelled_count > 0:
            msg += f"\nCancelled / Unprocessed: {cancelled_count}"
        QMessageBox.information(self, "Batch Complete", msg)

    def closeEvent(self, event):
        """Ensure batch worker is cleanly cancelled and waited on before exit."""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)
        event.accept()

    def _on_batch_error(self, error: str):
        self._reset_ui_state()
        self._refresh_table()
        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.txt_file_log.appendPlainText(f"[{time_str}] [ERROR] Batch execution error: {error}")
        self.txt_file_log.moveCursor(QTextCursor.End)
        QMessageBox.critical(self, "Batch Error", f"Batch execution error:\n{error}")

    def _cancel_batch(self):
        if self.worker and self.worker.isRunning():
            time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.txt_file_log.appendPlainText(f"[{time_str}] [WARNING] Batch cancellation requested by user...")
            self.txt_file_log.moveCursor(QTextCursor.End)
            self.worker.cancel()
            self.btn_cancel.setEnabled(False)

    def _reset_ui_state(self):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_add_files.setEnabled(True)
        self.btn_add_folder.setEnabled(True)
        self.btn_remove.setEnabled(True)
        self.btn_clear.setEnabled(True)
        self.rate_limit_frame.hide()
