"""条款征询对话框（round-162）——首次使用 / 条款改版时启动门禁。

只负责展示与收集「同意」，不写配置：接受后由调用方写入
``terms_accepted_version`` 并保存。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from .i18n import t
from .terms import TERMS_UPDATED, TERMS_VERSION, combined_text


class TermsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("terms.title"))
        self.setProperty("cls", "card")
        self.setModal(True)
        self.resize(720, 600)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(12)

        title = QLabel(t("terms.title"))
        title.setProperty("cls", "title")
        lay.addWidget(title)

        intro = QLabel(t("terms.intro"))
        intro.setProperty("cls", "sub")
        intro.setWordWrap(True)
        lay.addWidget(intro)

        version = QLabel(t("terms.version", version=TERMS_VERSION, date=TERMS_UPDATED))
        version.setProperty("cls", "sub")
        lay.addWidget(version)

        self.text = QTextBrowser()
        self.text.setPlainText(combined_text())
        self.text.setOpenExternalLinks(False)
        self.text.setFocusPolicy(Qt.NoFocus)
        lay.addWidget(self.text, stretch=1)

        self.agree = QCheckBox(t("terms.accept"))
        lay.addWidget(self.agree)

        row = QHBoxLayout()
        row.addStretch(1)
        self.quit_btn = QPushButton(t("terms.quit"))
        self.quit_btn.setMinimumHeight(36)
        self.quit_btn.clicked.connect(self.reject)
        self.continue_btn = QPushButton(t("terms.continue"))
        self.continue_btn.setProperty("cls", "accent")
        self.continue_btn.setMinimumHeight(36)
        self.continue_btn.setEnabled(False)
        self.continue_btn.clicked.connect(self.accept)
        row.addWidget(self.quit_btn)
        row.addWidget(self.continue_btn)
        lay.addLayout(row)

        self.agree.toggled.connect(self.continue_btn.setEnabled)

    def accept(self) -> None:
        if not self.agree.isChecked():
            return
        super().accept()
