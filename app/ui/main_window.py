"""
Main Application Window for Online Subtitle Translator.
Specialized application for translating subtitle (.srt) files into multiple target languages
(Persian, Arabic, Spanish, French, German, and more) using Google Gemini multi-model/multi-account
auto-rotation and Cloudflare Workers AI multi-account failover.
"""

from __future__ import annotations
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QComboBox,
    QProgressBar, QFileDialog, QMessageBox, QGroupBox, QStatusBar,
    QFrame, QScrollArea
)
from PySide6.QtCore import Qt, QTimer

from app.core.config import (
    APP_NAME, APP_VERSION,
    VERIFIED_TRANSLATION_PROVIDERS,
    SUPPORTED_TARGET_LANGUAGES,
    get_app_icon
)
from app.core.database import Database
from app.core.credential_manager import CredentialManager
from app.core.srt_parser import SRTParser
from app.services.translation_service import TranslationService
from app.services.batch_service import BatchService
from app.ui.components.batch_dialog import BatchDialog
from app.ui.components.credentials_dialog import CredentialsDialog
from app.ui.components.log_viewer_dialog import LogViewerDialog
from app.ui.styles import DARK_THEME_QSS
from app.workers.translation_worker import TranslationWorker

logger = logging.getLogger("OnlineSubtitleTranslator.UI")


class MainWindow(QMainWindow):
    """Primary application window for Online Subtitle Translator."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} — AI Subtitle Translator")
        self.resize(880, 680)
        self.setMinimumSize(800, 600)
        self.setStyleSheet(DARK_THEME_QSS)

        app_icon = get_app_icon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)

        # Core services
        self.db = Database()
        self.translation_service = TranslationService(database=self.db)
        self.batch_service = BatchService(translation_service=self.translation_service, database=self.db)

        # Active state
        self.active_worker: Optional[TranslationWorker] = None
        self.last_output_dir: Optional[Path] = None
        self.start_timestamp: float = 0.0

        # UI timer for elapsed time
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_elapsed_time)

        self._build_ui()
        self._populate_models()
        self._update_credentials_status()

    def _build_ui(self):
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        central_widget = QWidget()
        central_widget.setMinimumWidth(740)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(18, 14, 18, 14)

        # Header & Top Toolbars
        top_bar = QHBoxLayout()
        title_box = QVBoxLayout()
        lbl_title = QLabel("Online Subtitle Translator")
        lbl_title.setStyleSheet("font-size: 19px; font-weight: bold; color: #38bdf8;")
        lbl_sub = QLabel("Multi-Language AI Subtitle Translation • Auto-Rotating 10-Account Pools")
        lbl_sub.setStyleSheet("font-size: 12px; color: #94a3b8;")
        title_box.addWidget(lbl_title)
        title_box.addWidget(lbl_sub)
        top_bar.addLayout(title_box)
        top_bar.addStretch()

        self.btn_credentials = QPushButton("🔑 API Accounts (10 Slots)")
        self.btn_credentials.setObjectName("btn_secondary")
        self.btn_credentials.clicked.connect(self._open_credentials)
        top_bar.addWidget(self.btn_credentials)

        self.btn_batch = QPushButton("📁 Batch Translator")
        self.btn_batch.setObjectName("btn_secondary")
        self.btn_batch.clicked.connect(self._open_batch)
        top_bar.addWidget(self.btn_batch)

        self.btn_logs = QPushButton("📜 Logs")
        self.btn_logs.setObjectName("btn_secondary")
        self.btn_logs.clicked.connect(self._open_logs)
        top_bar.addWidget(self.btn_logs)

        main_layout.addLayout(top_bar)

        # Group 1: Subtitle Input & Target Language
        grp_input = QGroupBox("1. Subtitle File & Target Language")
        layout_input = QGridLayout(grp_input)
        layout_input.setSpacing(10)

        layout_input.addWidget(QLabel("Source SRT File:"), 0, 0)
        self.txt_srt_path = QLineEdit()
        self.txt_srt_path.setPlaceholderText("Select an existing .srt subtitle file...")
        self.txt_srt_path.textChanged.connect(self._on_srt_path_changed)
        layout_input.addWidget(self.txt_srt_path, 0, 1)

        self.btn_browse_srt = QPushButton("Browse...")
        self.btn_browse_srt.setObjectName("btn_secondary")
        self.btn_browse_srt.clicked.connect(self._browse_srt)
        layout_input.addWidget(self.btn_browse_srt, 0, 2)

        # Subtitle info label
        self.lbl_srt_info = QLabel("No subtitle loaded")
        self.lbl_srt_info.setStyleSheet("color: #64748b; font-size: 11px;")
        layout_input.addWidget(self.lbl_srt_info, 1, 1)

        # Target language selector
        layout_input.addWidget(QLabel("Target Language:"), 2, 0)
        self.combo_target_lang = QComboBox()
        for lang in SUPPORTED_TARGET_LANGUAGES:
            self.combo_target_lang.addItem(lang["name"], lang["code"])
        self.combo_target_lang.currentIndexChanged.connect(self._on_target_lang_changed)
        layout_input.addWidget(self.combo_target_lang, 2, 1)

        # Output file path
        layout_input.addWidget(QLabel("Output SRT Path:"), 3, 0)
        self.txt_output_path = QLineEdit()
        self.txt_output_path.setPlaceholderText("Default: auto-saved beside source SRT file")
        layout_input.addWidget(self.txt_output_path, 3, 1)

        self.btn_browse_out = QPushButton("Browse...")
        self.btn_browse_out.setObjectName("btn_secondary")
        self.btn_browse_out.clicked.connect(self._browse_output)
        layout_input.addWidget(self.btn_browse_out, 3, 2)

        main_layout.addWidget(grp_input)

        # Group 2: AI Translation Provider & Model
        grp_engine = QGroupBox("2. AI Engine & Model Selection")
        layout_engine = QGridLayout(grp_engine)
        layout_engine.setSpacing(10)

        layout_engine.addWidget(QLabel("Translation Model:"), 0, 0)
        self.combo_model = QComboBox()
        self.combo_model.currentIndexChanged.connect(self._on_model_changed)
        layout_engine.addWidget(self.combo_model, 0, 1)

        self.lbl_model_desc = QLabel()
        self.lbl_model_desc.setStyleSheet("color: #94a3b8; font-size: 11.5px;")
        self.lbl_model_desc.setWordWrap(True)
        layout_engine.addWidget(self.lbl_model_desc, 1, 1)

        self.lbl_accounts_status = QLabel()
        self.lbl_accounts_status.setStyleSheet("color: #38bdf8; font-size: 11px; font-weight: 500;")
        layout_engine.addWidget(self.lbl_accounts_status, 2, 1)

        main_layout.addWidget(grp_engine)

        # Rate Limit Alert Banner
        self.rate_limit_frame = QFrame()
        self.rate_limit_frame.setStyleSheet("""
            QFrame {
                background-color: #422006;
                border: 1px solid #f59e0b;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        rl_layout = QHBoxLayout(self.rate_limit_frame)
        self.lbl_rl_icon = QLabel("⏳")
        self.lbl_rl_message = QLabel("Rate limit reached. Automatically rotating accounts...")
        self.lbl_rl_message.setStyleSheet("color: #fbbf24; font-weight: bold; font-size: 12px;")
        rl_layout.addWidget(self.lbl_rl_icon)
        rl_layout.addWidget(self.lbl_rl_message, 1)
        self.rate_limit_frame.hide()
        main_layout.addWidget(self.rate_limit_frame)

        # Group 3: Execution & Progress
        grp_exec = QGroupBox("3. Translation Progress & Controls")
        layout_exec = QVBoxLayout(grp_exec)
        layout_exec.setSpacing(10)

        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_row.addWidget(self.progress_bar, 1)

        self.lbl_elapsed = QLabel("00:00")
        self.lbl_elapsed.setStyleSheet("font-family: monospace; font-size: 12px; color: #94a3b8;")
        progress_row.addWidget(self.lbl_elapsed)
        layout_exec.addLayout(progress_row)

        self.lbl_status = QLabel("Ready to translate")
        self.lbl_status.setStyleSheet("color: #cbd5e1; font-weight: 500;")
        layout_exec.addWidget(self.lbl_status)

        btn_row = QHBoxLayout()
        self.btn_translate = QPushButton("Translate Subtitle")
        self.btn_translate.setObjectName("btn_success")
        self.btn_translate.setStyleSheet("font-size: 13px; font-weight: bold; padding: 10px 24px;")
        self.btn_translate.clicked.connect(self._start_translation)
        btn_row.addWidget(self.btn_translate)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("btn_danger")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_translation)
        btn_row.addWidget(self.btn_cancel)

        self.btn_open_folder = QPushButton("Open Output Folder")
        self.btn_open_folder.setObjectName("btn_secondary")
        self.btn_open_folder.setEnabled(False)
        self.btn_open_folder.clicked.connect(self._open_output_folder)
        btn_row.addWidget(self.btn_open_folder)

        btn_row.addStretch()
        layout_exec.addLayout(btn_row)

        main_layout.addWidget(grp_exec)
        main_layout.addStretch()

        scroll_area.setWidget(central_widget)
        self.setCentralWidget(scroll_area)

        # Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Online Subtitle Translator ready.")

    def _populate_models(self):
        self.combo_model.clear()
        for p in VERIFIED_TRANSLATION_PROVIDERS:
            label = f"{p.display_name} — {p.model_display_name}"
            self.combo_model.addItem(label, (p.provider_id, p.model_id))
        self._on_model_changed()

    def _on_model_changed(self):
        data = self.combo_model.currentData()
        if not data:
            return
        prov_id, model_id = data
        p = next((x for x in VERIFIED_TRANSLATION_PROVIDERS if x.provider_id == prov_id and x.model_id == model_id), None)
        if p:
            self.lbl_model_desc.setText(
                f"• Provider: {p.display_name}\n"
                f"• Model: {p.model_id}\n"
                f"• Tier: {p.pricing_desc}\n"
                f"• Features: {p.free_tier_desc}"
            )
        self._update_credentials_status()

    def _update_credentials_status(self):
        gemini_accounts = CredentialManager.get_gemini_accounts()
        gemini_cfg = sum(1 for a in gemini_accounts if a["configured"])

        cf_accounts = CredentialManager.get_cloudflare_accounts()
        cf_cfg = sum(1 for a in cf_accounts if a["configured"])

        self.lbl_accounts_status.setText(
            f"Active Pools: Google Gemini ({gemini_cfg}/10 accounts configured) • "
            f"Cloudflare Workers AI ({cf_cfg}/10 accounts configured)"
        )

    def _browse_srt(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Subtitle File",
            "",
            "SRT Subtitle Files (*.srt)"
        )
        if file_path:
            self.txt_srt_path.setText(file_path)

    def _browse_output(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Select Output Subtitle File",
            self.txt_output_path.text(),
            "SRT Subtitle Files (*.srt)"
        )
        if file_path:
            self.txt_output_path.setText(file_path)

    def _on_srt_path_changed(self, text: str):
        p = Path(text)
        if p.exists() and p.is_file():
            try:
                sub = SRTParser.parse_file(p)
                self.lbl_srt_info.setText(
                    f"✓ Loaded: {len(sub.cues)} subtitle cues ({p.stat().st_size / 1024:.1f} KB)"
                )
                self.lbl_srt_info.setStyleSheet("color: #22c55e; font-size: 11px;")
            except Exception as e:
                self.lbl_srt_info.setText(f"Error reading SRT: {e}")
                self.lbl_srt_info.setStyleSheet("color: #ef4444; font-size: 11px;")

            # Suggest default output path
            target_lang = self.combo_target_lang.currentData() or "fa"
            default_out = TranslationService.get_default_translated_path(p, target_lang)
            self.txt_output_path.setText(str(default_out))
        else:
            self.lbl_srt_info.setText("No subtitle loaded")
            self.lbl_srt_info.setStyleSheet("color: #64748b; font-size: 11px;")

    def _on_target_lang_changed(self):
        p_str = self.txt_srt_path.text().strip()
        if p_str:
            p = Path(p_str)
            if p.exists() and p.is_file():
                target_lang = self.combo_target_lang.currentData() or "fa"
                default_out = TranslationService.get_default_translated_path(p, target_lang)
                self.txt_output_path.setText(str(default_out))

    def _open_credentials(self):
        dlg = CredentialsDialog(self)
        dlg.exec()
        self._update_credentials_status()

    def _open_batch(self):
        dlg = BatchDialog(self.batch_service, self)
        dlg.exec()

    def _open_logs(self):
        dlg = LogViewerDialog(self)
        dlg.exec()

    def _start_translation(self):
        srt_path_str = self.txt_srt_path.text().strip()
        if not srt_path_str:
            QMessageBox.warning(self, "Missing Subtitle", "Please select an existing SRT subtitle file.")
            return

        srt_path = Path(srt_path_str)
        if not srt_path.exists():
            QMessageBox.critical(self, "File Not Found", f"The subtitle file does not exist:\n{srt_path}")
            return

        target_lang = self.combo_target_lang.currentData() or "fa"
        out_path_str = self.txt_output_path.text().strip()
        out_path = Path(out_path_str) if out_path_str else TranslationService.get_default_translated_path(srt_path, target_lang)

        data = self.combo_model.currentData()
        if not data:
            QMessageBox.warning(self, "No Model", "Please select a translation model.")
            return
        prov_id, model_id = data

        # Check credentials
        if prov_id == "gemini":
            accounts = CredentialManager.get_gemini_accounts()
            if not any(a["configured"] for a in accounts):
                QMessageBox.warning(
                    self,
                    "Credentials Required",
                    "No Google Gemini API Key configured.\nPlease configure at least one account in 'API Accounts'."
                )
                self._open_credentials()
                return
        elif prov_id == "cloudflare":
            accounts = CredentialManager.get_cloudflare_accounts()
            if not any(a["configured"] for a in accounts):
                QMessageBox.warning(
                    self,
                    "Credentials Required",
                    "No Cloudflare Account configured.\nPlease configure at least one account in 'API Accounts'."
                )
                self._open_credentials()
                return

        # Prepare UI
        self.btn_translate.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_open_folder.setEnabled(False)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Initializing translation...")
        self.rate_limit_frame.hide()

        self.start_timestamp = time.time()
        self.lbl_elapsed.setText("00:00")
        self.timer.start(1000)

        self.active_worker = TranslationWorker(
            translation_service=self.translation_service,
            english_srt_path=srt_path,
            provider_id=prov_id,
            model_id=model_id,
            target_lang=target_lang,
            output_path=out_path
        )
        self.active_worker.progress.connect(self._on_worker_progress)
        self.active_worker.rate_limit_wait.connect(self._on_rate_limit)
        self.active_worker.rate_limit_cleared.connect(self._on_rate_limit_cleared)
        self.active_worker.finished.connect(self._on_worker_finished)
        self.active_worker.failed.connect(self._on_worker_failed)
        self.active_worker.start()

    def _on_worker_progress(self, stage: str, pct: int):
        self.progress_bar.setValue(pct)
        self.lbl_status.setText(stage)
        self.status_bar.showMessage(stage)

    def _on_rate_limit(self, provider: str, remaining_sec: int, attempt: int, reason: str):
        self.rate_limit_frame.show()
        self.lbl_rl_message.setText(
            f"Rate Limit ({provider}) — Attempt #{attempt}: Auto-rotating / waiting {remaining_sec}s..."
        )

    def _on_rate_limit_cleared(self, provider: str):
        self.rate_limit_frame.hide()

    def _on_worker_finished(self, out_path_str: str):
        self.timer.stop()
        self.progress_bar.setValue(100)
        self.lbl_status.setText("Translation completed successfully!")
        self.status_bar.showMessage("Translation finished.")
        self.rate_limit_frame.hide()

        out_path = Path(out_path_str)
        self.last_output_dir = out_path.parent
        self.btn_open_folder.setEnabled(True)
        self.btn_translate.setEnabled(True)
        self.btn_cancel.setEnabled(False)

        QMessageBox.information(
            self,
            "Success",
            f"Subtitle translated successfully!\n\nSaved to:\n{out_path.name}"
        )

    def _on_worker_failed(self, error: str):
        self.timer.stop()
        self.lbl_status.setText("Translation failed.")
        self.status_bar.showMessage("Translation error.")
        self.rate_limit_frame.hide()

        self.btn_translate.setEnabled(True)
        self.btn_cancel.setEnabled(False)

        QMessageBox.critical(self, "Translation Error", f"An error occurred during translation:\n\n{error}")

    def _cancel_translation(self):
        if self.active_worker and self.active_worker.isRunning():
            self.lbl_status.setText("Cancelling translation...")
            self.active_worker.cancel()
            self.btn_cancel.setEnabled(False)

    def _open_output_folder(self):
        folder = self.last_output_dir or Path(self.txt_output_path.text().strip()).parent
        if folder.exists():
            import subprocess
            subprocess.run(f'explorer "{folder}"', shell=True)

    def _update_elapsed_time(self):
        elapsed = int(time.time() - self.start_timestamp)
        mins = elapsed // 60
        secs = elapsed % 60
        self.lbl_elapsed.setText(f"{mins:02d}:{secs:02d}")
