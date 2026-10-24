"""
Secure API Credentials configuration dialog for Online Subtitle Translator.
Stores keys directly in Windows Credential Manager. Zero plaintext storage.
Supports up to 10 Gemini accounts and 10 Cloudflare accounts for seamless auto-rotation.
"""

from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QGridLayout, QMessageBox, QTabWidget,
    QWidget, QComboBox, QFrame
)
from PySide6.QtCore import Qt
from app.core.config import get_app_icon
from app.core.credential_manager import CredentialManager


class CredentialsDialog(QDialog):
    """Dialog for securely configuring multi-account Gemini and Cloudflare pools."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Online Subtitle Translator — API Credentials & Multi-Account Rotation")
        app_icon = get_app_icon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)
        self.setMinimumWidth(620)
        self.setMinimumHeight(480)
        self._build_ui()
        self._refresh_all_accounts()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        sec_note = QLabel(
            "Security Guarantee: All API keys and tokens are securely stored in the Windows Credential Manager.\n"
            "Each provider supports up to 10 accounts. If an account hits a rate limit or daily quota, "
            "the translator automatically switches to the next account."
        )
        sec_note.setStyleSheet("color: #38bdf8; font-size: 11.5px; font-weight: 500;")
        sec_note.setWordWrap(True)
        layout.addWidget(sec_note)

        tabs = QTabWidget()

        # -------------------------------------------------------------
        # Tab 1: Google Gemini (10 Accounts)
        # -------------------------------------------------------------
        gemini_tab = QWidget()
        gem_layout = QVBoxLayout(gemini_tab)
        gem_layout.setSpacing(12)

        gem_desc = QLabel(
            "Gemini Multi-Account Rotation:\n"
            "When translating, models (3.5-flash, 3.8-flash, flash-lite, etc.) are rotated. "
            "If all models on an account encounter rate limits (429), the next Gemini account is tried automatically."
        )
        gem_desc.setStyleSheet("color: #94a3b8; font-size: 11px;")
        gem_desc.setWordWrap(True)
        gem_layout.addWidget(gem_desc)

        slot_box = QHBoxLayout()
        slot_box.addWidget(QLabel("Select Gemini Account Slot:"))
        self.combo_gemini_slot = QComboBox()
        for i in range(1, 11):
            label = f"Account #{i} (Primary)" if i == 1 else f"Account #{i}"
            self.combo_gemini_slot.addItem(label, i)
        self.combo_gemini_slot.currentIndexChanged.connect(self._on_gemini_slot_changed)
        slot_box.addWidget(self.combo_gemini_slot, 1)
        gem_layout.addLayout(slot_box)

        # Editor box
        editor_group = QGroupBox("Edit Account Credentials")
        ed_layout = QGridLayout(editor_group)

        self.txt_gemini_key = QLineEdit()
        self.txt_gemini_key.setEchoMode(QLineEdit.Password)
        self.txt_gemini_key.setPlaceholderText("Enter Google AI Studio API Key (AIzaSy...)")
        ed_layout.addWidget(QLabel("API Key:"), 0, 0)
        ed_layout.addWidget(self.txt_gemini_key, 0, 1)

        btn_tgl_gem = QPushButton("Show")
        btn_tgl_gem.setObjectName("btn_secondary")
        btn_tgl_gem.clicked.connect(lambda: self._toggle_echo(self.txt_gemini_key, btn_tgl_gem))
        ed_layout.addWidget(btn_tgl_gem, 0, 2)

        gem_btn_row = QHBoxLayout()
        self.btn_save_gemini = QPushButton("Save This Account")
        self.btn_save_gemini.setObjectName("btn_primary")
        self.btn_save_gemini.clicked.connect(self._save_current_gemini)
        gem_btn_row.addWidget(self.btn_save_gemini)

        self.btn_clear_gemini = QPushButton("Clear This Slot")
        self.btn_clear_gemini.setObjectName("btn_danger")
        self.btn_clear_gemini.clicked.connect(self._clear_current_gemini)
        gem_btn_row.addWidget(self.btn_clear_gemini)

        ed_layout.addLayout(gem_btn_row, 1, 0, 1, 3)
        gem_layout.addWidget(editor_group)

        # Accounts Overview
        overview_group = QGroupBox("Configured Gemini Accounts Status (1-10)")
        ov_layout = QVBoxLayout(overview_group)
        self.lbl_gemini_overview = QLabel()
        self.lbl_gemini_overview.setStyleSheet("font-family: monospace; font-size: 11px; color: #cbd5e1;")
        ov_layout.addWidget(self.lbl_gemini_overview)
        gem_layout.addWidget(overview_group)
        gem_layout.addStretch()

        tabs.addTab(gemini_tab, "Google Gemini Pool (10 Accounts)")

        # -------------------------------------------------------------
        # Tab 2: Cloudflare Workers AI (10 Accounts)
        # -------------------------------------------------------------
        cf_tab = QWidget()
        cf_layout = QVBoxLayout(cf_tab)
        cf_layout.setSpacing(12)

        cf_desc = QLabel(
            "Cloudflare Multi-Account Rotation:\n"
            "Each Cloudflare account provides 10,000 free daily Neurons. "
            "If Account #1 runs out of daily quota (429), it switches to Account #2, up to 10 accounts."
        )
        cf_desc.setStyleSheet("color: #94a3b8; font-size: 11px;")
        cf_desc.setWordWrap(True)
        cf_layout.addWidget(cf_desc)

        cf_slot_box = QHBoxLayout()
        cf_slot_box.addWidget(QLabel("Select Cloudflare Account Slot:"))
        self.combo_cf_slot = QComboBox()
        for i in range(1, 11):
            label = f"Account #{i} (Primary)" if i == 1 else f"Account #{i}"
            self.combo_cf_slot.addItem(label, i)
        self.combo_cf_slot.currentIndexChanged.connect(self._on_cf_slot_changed)
        cf_slot_box.addWidget(self.combo_cf_slot, 1)
        cf_layout.addLayout(cf_slot_box)

        cf_editor_group = QGroupBox("Edit Account Credentials")
        cf_ed_layout = QGridLayout(cf_editor_group)

        self.txt_cf_token = QLineEdit()
        self.txt_cf_token.setEchoMode(QLineEdit.Password)
        self.txt_cf_token.setPlaceholderText("Enter Cloudflare API Token")
        cf_ed_layout.addWidget(QLabel("API Token:"), 0, 0)
        cf_ed_layout.addWidget(self.txt_cf_token, 0, 1)

        btn_tgl_cf = QPushButton("Show")
        btn_tgl_cf.setObjectName("btn_secondary")
        btn_tgl_cf.clicked.connect(lambda: self._toggle_echo(self.txt_cf_token, btn_tgl_cf))
        cf_ed_layout.addWidget(btn_tgl_cf, 0, 2)

        self.txt_cf_account = QLineEdit()
        self.txt_cf_account.setPlaceholderText("Enter Cloudflare Account ID")
        cf_ed_layout.addWidget(QLabel("Account ID:"), 1, 0)
        cf_ed_layout.addWidget(self.txt_cf_account, 1, 1, 1, 2)

        cf_btn_row = QHBoxLayout()
        self.btn_save_cf = QPushButton("Save This Account")
        self.btn_save_cf.setObjectName("btn_primary")
        self.btn_save_cf.clicked.connect(self._save_current_cf)
        cf_btn_row.addWidget(self.btn_save_cf)

        self.btn_clear_cf = QPushButton("Clear This Slot")
        self.btn_clear_cf.setObjectName("btn_danger")
        self.btn_clear_cf.clicked.connect(self._clear_current_cf)
        cf_btn_row.addWidget(self.btn_clear_cf)

        cf_ed_layout.addLayout(cf_btn_row, 2, 0, 1, 3)
        cf_layout.addWidget(cf_editor_group)

        cf_overview_group = QGroupBox("Configured Cloudflare Accounts Status (1-10)")
        cf_ov_layout = QVBoxLayout(cf_overview_group)
        self.lbl_cf_overview = QLabel()
        self.lbl_cf_overview.setStyleSheet("font-family: monospace; font-size: 11px; color: #cbd5e1;")
        cf_ov_layout.addWidget(self.lbl_cf_overview)
        cf_layout.addWidget(cf_overview_group)
        cf_layout.addStretch()

        tabs.addTab(cf_tab, "Cloudflare Workers AI Pool (10 Accounts)")

        layout.addWidget(tabs)

        # Dialog buttons
        bottom_bar = QHBoxLayout()
        bottom_bar.addStretch()
        btn_close = QPushButton("Close")
        btn_close.clicked.connect(self.accept)
        bottom_bar.addWidget(btn_close)
        layout.addLayout(bottom_bar)

    def _toggle_echo(self, line_edit: QLineEdit, toggle_btn: QPushButton):
        if line_edit.echoMode() == QLineEdit.Password:
            line_edit.setEchoMode(QLineEdit.Normal)
            toggle_btn.setText("Hide")
        else:
            line_edit.setEchoMode(QLineEdit.Password)
            toggle_btn.setText("Show")

    # ---------------- Gemini Slot Handling ----------------
    def _on_gemini_slot_changed(self, idx: int):
        slot_idx = self.combo_gemini_slot.currentData()
        accounts = CredentialManager.get_gemini_accounts()
        curr = next((a for a in accounts if a["index"] == slot_idx), None)
        if curr and curr["api_key"]:
            self.txt_gemini_key.setText(curr["api_key"])
        else:
            self.txt_gemini_key.clear()

    def _save_current_gemini(self):
        slot_idx = self.combo_gemini_slot.currentData()
        key = self.txt_gemini_key.text().strip()
        if not key:
            QMessageBox.warning(self, "Validation", "Please enter an API Key before saving.")
            return
        CredentialManager.set_gemini_account(slot_idx, key)
        self._refresh_gemini_overview()
        QMessageBox.information(self, "Saved", f"Gemini Account #{slot_idx} saved securely.")

    def _clear_current_gemini(self):
        slot_idx = self.combo_gemini_slot.currentData()
        if QMessageBox.question(self, "Clear Account", f"Remove credentials for Gemini Account #{slot_idx}?") == QMessageBox.Yes:
            CredentialManager.delete_gemini_account(slot_idx)
            self.txt_gemini_key.clear()
            self._refresh_gemini_overview()

    def _refresh_gemini_overview(self):
        accounts = CredentialManager.get_gemini_accounts()
        lines = []
        configured_count = 0
        for a in accounts:
            idx = a["index"]
            is_cfg = a["configured"]
            status = f"CONFIGURED ({CredentialManager.mask_key(a['api_key'])})" if is_cfg else "NOT CONFIGURED"
            if is_cfg:
                configured_count += 1
            lines.append(f"Slot {idx:2d}: {status}")

        summary = f"Total configured: {configured_count} / 10\n" + "\n".join(lines[:5]) + "\n" + "\n".join(lines[5:])
        self.lbl_gemini_overview.setText(summary)

    # ---------------- Cloudflare Slot Handling ----------------
    def _on_cf_slot_changed(self, idx: int):
        slot_idx = self.combo_cf_slot.currentData()
        accounts = CredentialManager.get_cloudflare_accounts()
        curr = next((a for a in accounts if a["index"] == slot_idx), None)
        if curr:
            self.txt_cf_token.setText(curr["api_key"])
            self.txt_cf_account.setText(curr["account_id"])
        else:
            self.txt_cf_token.clear()
            self.txt_cf_account.clear()

    def _save_current_cf(self):
        slot_idx = self.combo_cf_slot.currentData()
        token = self.txt_cf_token.text().strip()
        acct = self.txt_cf_account.text().strip()
        if not token or not acct:
            QMessageBox.warning(self, "Validation", "Please enter both API Token and Account ID before saving.")
            return
        CredentialManager.set_cloudflare_account(slot_idx, acct, token)
        self._refresh_cf_overview()
        QMessageBox.information(self, "Saved", f"Cloudflare Account #{slot_idx} saved securely.")

    def _clear_current_cf(self):
        slot_idx = self.combo_cf_slot.currentData()
        if QMessageBox.question(self, "Clear Account", f"Remove credentials for Cloudflare Account #{slot_idx}?") == QMessageBox.Yes:
            CredentialManager.delete_cloudflare_account(slot_idx)
            self.txt_cf_token.clear()
            self.txt_cf_account.clear()
            self._refresh_cf_overview()

    def _refresh_cf_overview(self):
        accounts = CredentialManager.get_cloudflare_accounts()
        lines = []
        configured_count = 0
        for a in accounts:
            idx = a["index"]
            is_cfg = a["configured"]
            status = f"CONFIGURED ({CredentialManager.mask_key(a['account_id'])})" if is_cfg else "NOT CONFIGURED"
            if is_cfg:
                configured_count += 1
            lines.append(f"Slot {idx:2d}: {status}")

        summary = f"Total configured: {configured_count} / 10\n" + "\n".join(lines[:5]) + "\n" + "\n".join(lines[5:])
        self.lbl_cf_overview.setText(summary)

    def _refresh_all_accounts(self):
        self._on_gemini_slot_changed(0)
        self._refresh_gemini_overview()
        self._on_cf_slot_changed(0)
        self._refresh_cf_overview()
