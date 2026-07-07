from __future__ import annotations

import re
import sqlite3
import unicodedata
from pathlib import Path

from .llm import LocalLLM
from .pipeline import iter_documents, sync_folder
from .storage import FIELDS, export_csv

REVIEW_ROW_COLOR = "#3a2d14"
VISIBLE_FIELDS = ["so_van_ban", "ten_van_ban", "co_quan_phat_hanh", "ngay_ban_hanh", "loai_van_ban", "trich_yeu"]
APP_STATE_PATH = Path("data/desktop_state.txt")
SEARCH_FIELDS = ["so_van_ban", "ten_van_ban", "co_quan_phat_hanh", "loai_van_ban"]

FIELD_LABELS = {
    "so_van_ban": "Số văn bản",
    "ten_van_ban": "Tên văn bản",
    "co_quan_phat_hanh": "Cơ quan phát hành",
    "ngay_ban_hanh": "Ngày phát hành",
    "loai_van_ban": "Loại văn bản",
    "trich_yeu": "Trích yếu",
}

DARK_STYLE = """
QMainWindow {
    background-color: #0a1128;
}
QWidget {
    background-color: #0a1128;
    color: #e2e8f0;
    font-family: 'Segoe UI', 'Segoe UI Semibold', 'Segoe UI Emoji', sans-serif;
    font-size: 13px;
}
QLabel#app_title_label {
    font-size: 20px;
    font-weight: bold;
    color: #ffffff;
    padding: 10px 5px;
    background-color: transparent;
}
QTableWidget {
    background-color: #101f42;
    alternate-background-color: #172a5a;
    gridline-color: #1e3a8a;
    border: 1px solid #1e3a8a;
    border-radius: 8px;
    color: #e2e8f0;
}
QTableWidget::item {
    padding: 6px;
    border-bottom: 1px solid #1e3a8a;
}
QTableWidget::item:selected {
    background-color: #0284c7;
    color: #ffffff;
}
QHeaderView::section {
    background-color: #172a5a;
    color: #93c5fd;
    padding: 8px;
    border: none;
    border-bottom: 2px solid #1e3a8a;
    font-weight: bold;
}
QHeaderView::section:horizontal {
    border-right: 1px solid #1e3a8a;
}
QTableCornerButton::section {
    background-color: #172a5a;
    border: none;
    border-bottom: 2px solid #1e3a8a;
    border-right: 1px solid #1e3a8a;
}
QLineEdit, QTextEdit {
    background-color: #101f42;
    border: 1px solid #1e3a8a;
    border-radius: 6px;
    color: #ffffff;
    padding: 8px;
}
QLineEdit:focus, QTextEdit:focus {
    border: 1px solid #38bdf8;
}
QComboBox {
    background-color: #101f42;
    border: 1px solid #1e3a8a;
    border-radius: 6px;
    padding: 6px 12px;
    color: #ffffff;
    min-height: 20px;
}
QComboBox::drop-down {
    border: 0px;
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #101f42;
    border: 1px solid #1e3a8a;
    selection-background-color: #0284c7;
    selection-color: #ffffff;
    color: #ffffff;
}
QPushButton {
    background-color: #172a5a;
    border: 1px solid #1e3a8a;
    color: #e2e8f0;
    padding: 8px 16px;
    border-radius: 6px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #1e3a8a;
    border-color: #3b82f6;
}
QPushButton:pressed {
    background-color: #0f172a;
}
QPushButton:disabled {
    background-color: #0f172a;
    color: #64748b;
    border-color: #1e293b;
}
QPushButton#scan_btn, QPushButton#chat_send {
    background-color: #0284c7;
    border: 1px solid #38bdf8;
    color: #ffffff;
}
QPushButton#scan_btn:hover, QPushButton#chat_send:hover {
    background-color: #0ea5e9;
}
QPushButton#scan_btn:pressed, QPushButton#chat_send:pressed {
    background-color: #0369a1;
}
QPushButton#history_btn, QPushButton#settings_btn {
    font-size: 14px;
    padding: 6px 10px;
    min-width: 20px;
}
QScrollBar:vertical {
    background-color: #0a1128;
    width: 10px;
    margin: 0px;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background-color: #1e3a8a;
    min-height: 20px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background-color: #3b82f6;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QSplitter::handle {
    background-color: #1e3a8a;
}
QLabel#status_lbl {
    color: #94a3b8;
    font-size: 11px;
    background-color: transparent;
}
QWidget#selected_row_panel {
    background-color: #101f42;
    border: 1px solid #1e3a8a;
    border-radius: 8px;
}
QLabel#author_label {
    color: #94a3b8;
    background-color: transparent;
    font-weight: bold;
}
"""


def _save_selected_folder(folder: Path) -> None:
    APP_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    APP_STATE_PATH.write_text(str(folder), encoding="utf-8")


def _load_selected_folder() -> Path | None:
    try:
        folder = Path(APP_STATE_PATH.read_text(encoding="utf-8").strip())
    except OSError:
        return None
    return folder if folder.exists() else None


def _infer_folder_from_rows(rows: list[dict[str, object]]) -> Path | None:
    paths = [Path(str(row.get("original_path") or "")) for row in rows if row.get("original_path")]
    folders = [path.parent for path in paths if path.is_absolute()] or [path.parent for path in paths]
    if not folders:
        return None
    return max(folders, key=folders.count)


def _is_review_value(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _status_text(row_count: int, prefix: str = "Đã tải") -> str:
    return f"{prefix} {row_count} file."


def _normalize_search_text(value: object) -> str:
    text = unicodedata.normalize("NFD", str(value or "").casefold())
    return "".join(char for char in text if unicodedata.category(char) != "Mn")


def _filter_rows(rows: list[dict[str, object]], field: str, query: str) -> list[dict[str, object]]:
    normalized_query = _normalize_search_text(query).strip()
    if not normalized_query or field not in SEARCH_FIELDS:
        return rows
    return [row for row in rows if normalized_query in _normalize_search_text(row.get(field))]


def _select_fields(existing_columns: set[str]) -> list[str]:
    return [field if field in existing_columns else "''" for field in FIELDS]


def _folder_filter(folder: Path | None) -> tuple[str, tuple[str, ...]]:
    if folder is None:
        return "", ()
    folder_text = str(folder).rstrip("\\/")
    return " WHERE original_path LIKE ? OR original_path LIKE ?", (f"{folder_text}\\%", f"{folder_text}/%")


def _progress_text(current: int, total: int, file_name: str | None = None, action: str = "Đang xử lý") -> str:
    if total <= 0:
        return "Không tìm thấy file được hỗ trợ trong thư mục đã chọn."
    percent = round(current / total * 100)
    suffix = f" - {file_name}" if file_name else ""
    return f"{action} {current}/{total} file ({percent}%){suffix}"

def _folder_signature(folder: Path | None) -> tuple[tuple[str, int, int], ...]:
    if folder is None or not folder.exists():
        return ()
    return tuple(
        sorted(
            (str(path), path.stat().st_size, path.stat().st_mtime_ns)
            for path in iter_documents(folder)
            if path.exists()
        )
    )


def _load_document_rows(db_path: Path, folder: Path | None = None) -> list[dict[str, object]]:
    if not db_path.exists():
        return []
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(documents)")}
        where_clause, params = _folder_filter(folder)
        selected = _select_fields(columns)
        rows = list(
            conn.execute(
                f"SELECT {', '.join(selected)} FROM documents{where_clause} ORDER BY file_name",
                params,
            )
        )
    return [dict(zip(FIELDS, row)) for row in rows]


def _open_path_from_row(row: dict[str, object]) -> str | None:
    link = str(row.get("link_goc") or "")
    if link.startswith("file://"):
        return link
    original_path = str(row.get("original_path") or "")
    return Path(original_path).resolve().as_uri() if original_path else None


def _read_wiki(path: object) -> str:
    wiki_path = Path(str(path or ""))
    if not wiki_path.exists():
        return ""
    return wiki_path.read_text(encoding="utf-8", errors="ignore")


def _keywords(text: str) -> set[str]:
    return {word.lower() for word in re.findall(r"[\w/]{3,}", text, flags=re.UNICODE)}


def _build_chat_context(
    rows: list[dict[str, object]],
    question: str,
    selected_index: int | None = None,
    selected_only: bool = True,
    max_chars: int = 9000,
) -> tuple[str, list[str]]:
    candidates = rows
    if selected_only and selected_index is not None and 0 <= selected_index < len(rows):
        candidates = [rows[selected_index]]
    elif not selected_only:
        question_words = _keywords(question)
        candidates = sorted(
            rows,
            key=lambda row: len(question_words & _keywords(" ".join(str(row.get(field) or "") for field in VISIBLE_FIELDS))),
            reverse=True,
        )[:5]

    parts: list[str] = []
    sources: list[str] = []
    for row in candidates:
        wiki = _read_wiki(row.get("wiki_path"))
        if not wiki:
            continue
        source = f"{row.get('so_van_ban') or ''} - {row.get('ten_van_ban') or row.get('file_name') or ''}".strip(" -")
        sources.append(source)
        parts.append(f"# SOURCE: {source}\n{wiki[:max_chars]}")
        if sum(len(part) for part in parts) >= max_chars:
            break
    return "\n\n".join(parts)[:max_chars], sources


def run(db_path: Path) -> int:
    try:
        from PySide6.QtCore import QObject, QThread, Qt, QUrl, Signal, QTimer, QRectF
        from PySide6.QtGui import QColor, QDesktopServices, QPainter, QFont, QAction, QPen, QIcon
        from PySide6.QtWidgets import (
            QApplication,
            QComboBox,
            QFileDialog,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMainWindow,
            QPushButton,
            QSplitter,
            QTableWidget,
            QTableWidgetItem,
            QTextEdit,
            QVBoxLayout,
            QWidget,
            QDialog,
            QDialogButtonBox,
            QDoubleSpinBox,
            QSpinBox,
            QFormLayout,
            QMenu,
            QHeaderView,
            QGridLayout,
            QSizePolicy,
        )
    except ImportError as exc:
        raise SystemExit("PySide6 chua duoc bundle. Dung CLI: python -m phanloaivanban scan <folder>") from exc

    class CircularProgressIndicator(QWidget):
        def __init__(self, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.value = 0
            self.max_value = 100
            self.angle = 0
            self.timer: QTimer | None = None
            self.is_spinning = False
            self.setFixedSize(36, 36)

        def set_value(self, val: int) -> None:
            self.value = max(0, min(val, 100))
            if 0 < self.value < 100:
                self.start_spinning()
            else:
                self.stop_spinning()
            self.update()

        def start_spinning(self) -> None:
            self.is_spinning = True
            if self.timer is None:
                self.timer = QTimer(self)
                self.timer.timeout.connect(self._rotate)
            if not self.timer.isActive():
                self.timer.start(30)  # Rotate every 30ms

        def stop_spinning(self) -> None:
            self.is_spinning = False
            if self.timer is not None:
                self.timer.stop()
            self.update()

        def _rotate(self) -> None:
            self.angle = (self.angle - 6) % 360
            self.update()

        def paintEvent(self, event) -> None:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            
            rect = QRectF(3.0, 3.0, float(self.width() - 6), float(self.height() - 6))
            
            # Draw background track
            pen_bg = QPen(QColor("#1e3a8a"), 3.0)
            painter.setPen(pen_bg)
            painter.drawEllipse(rect)
            
            # Draw active arc
            pen_active = QPen(QColor("#38bdf8"), 3.0)
            painter.setPen(pen_active)
            
            if self.is_spinning:
                painter.drawArc(rect, self.angle * 16, 120 * 16)
            else:
                span_angle = -int((self.value / self.max_value) * 360 * 16)
                painter.drawArc(rect, 90 * 16, span_angle)
                
            font = QFont("Segoe UI", 7)
            painter.setFont(font)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{self.value}%")

    class SettingsDialog(QDialog):
        def __init__(self, current_temp: float, current_max_tokens: int, parent: QWidget | None = None) -> None:
            super().__init__(parent)
            self.setWindowTitle("LLM Parameter Settings")
            self.setModal(True)
            self.resize(320, 160)
            
            # Apply same dark style
            self.setStyleSheet(DARK_STYLE)
            
            layout = QVBoxLayout(self)
            form = QFormLayout()
            
            self.temp_spin = QDoubleSpinBox()
            self.temp_spin.setRange(0.0, 1.0)
            self.temp_spin.setSingleStep(0.1)
            self.temp_spin.setValue(current_temp)
            
            self.tokens_spin = QSpinBox()
            self.tokens_spin.setRange(128, 2048)
            self.tokens_spin.setSingleStep(64)
            self.tokens_spin.setValue(current_max_tokens)
            
            form.addRow("Temperature (0.0 - 1.0):", self.temp_spin)
            form.addRow("Max Tokens:", self.tokens_spin)
            
            layout.addLayout(form)
            
            self.buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )
            self.buttons.accepted.connect(self.accept)
            self.buttons.rejected.connect(self.reject)
            layout.addWidget(self.buttons)

        def get_values(self) -> tuple[float, int]:
            return self.temp_spin.value(), self.tokens_spin.value()

    class ScanWorker(QObject):
        progress = Signal(int, int, str, str)
        finished = Signal(int, int, int, str)
        failed = Signal(str)

        def __init__(self, folder: Path, db_path: Path, csv_path: Path) -> None:
            super().__init__()
            self.folder = folder
            self.db_path = db_path
            self.csv_path = csv_path

        def run(self) -> None:
            try:
                total = len(iter_documents(self.folder))
                self.progress.emit(0, total, "", "Đang chuẩn bị")

                def report(current: int, total_count: int, path: Path, action: str = "Đang xử lý") -> None:
                    self.progress.emit(current, total_count, path.name, action)

                records, deleted_count = sync_folder(self.folder, self.db_path, self.csv_path, progress_callback=report)
                review_count = sum(1 for record in records if record.needs_review)
                self.finished.emit(len(records), deleted_count, review_count, str(self.csv_path))
            except Exception as exc:  # pragma: no cover - GUI runtime path
                self.failed.emit(str(exc))

    class ChatWorker(QObject):
        finished = Signal(str, str)
        failed = Signal(str)

        def __init__(self, question: str, context: str, sources: list[str], temperature: float, max_tokens: int) -> None:
            super().__init__()
            self.question = question
            self.context = context
            self.sources = sources
            self.temperature = temperature
            self.max_tokens = max_tokens

        def run(self) -> None:
            llm = LocalLLM(temperature=self.temperature, max_tokens=self.max_tokens)
            try:
                if not self.context:
                    self.failed.emit("Không có nội dung wiki cho câu hỏi này.")
                    return
                answer = llm.ask(self.question, self.context)
                if not answer:
                    self.failed.emit("LLM chưa sẵn sàng hoặc không phản hồi.")
                    return
                source_text = "; ".join(self.sources) if self.sources else "không rõ"
                self.finished.emit(answer, source_text)
            finally:
                llm.close()

    class Window(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("MiDoc - Classify")
            
            # Set window icon
            icon_path = Path("D:/PROJECT/Agentic-AI/phanloaivanban/logo.ico")
            if not icon_path.exists():
                icon_path = Path(__file__).parents[2] / "logo.ico"
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path.resolve())))
                
            self.db_path = db_path
            self.all_rows: list[dict[str, object]] = []
            self.rows: list[dict[str, object]] = []
            self.current_scan_folder: Path | None = None
            self.scan_thread: QThread | None = None
            self.scan_worker: ScanWorker | None = None
            self.chat_thread: QThread | None = None
            self.chat_worker: ChatWorker | None = None
            self.synced_folder_signature: tuple[tuple[str, int, int], ...] = ()

            # LLM parameters
            self.llm_temperature = 0.0
            self.llm_max_tokens = 768

            # Chat history session management
            self.chat_sessions: list[dict[str, object]] = []
            self.current_session_questions: list[str] = []

            # 1. Main Title Header
            self.app_title_label = QLabel("<span style='color:#22c55e'>MiDoc</span><span style='color:#f97316'> - Classify</span>")
            self.app_title_label.setObjectName("app_title_label")
            self.app_title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

            self.search_field = QComboBox()
            self.search_field.addItems([FIELD_LABELS[field] for field in SEARCH_FIELDS])
            self.search_field.setFixedWidth(160)
            self.search_input = QLineEdit()
            self.search_input.setPlaceholderText("Nhập thông tin tìm kiếm...")
            self.search_input.setFixedWidth(240)
            self.search_input.returnPressed.connect(self.apply_search)
            self.search_btn = QPushButton("🔍")
            self.search_btn.setToolTip("Tìm kiếm")
            self.search_btn.clicked.connect(lambda: self.apply_search())

            header_layout = QHBoxLayout()
            header_layout.addWidget(self.app_title_label, stretch=1)
            header_layout.addWidget(self.search_field)
            header_layout.addWidget(self.search_input)
            header_layout.addWidget(self.search_btn)

            # Author Label (Góc dưới bên phải)
            self.author_label = QLabel("Phạm Văn Long - HAVS")
            self.author_label.setObjectName("author_label")

            # Selection Labels Panel (Hiển thị thông tin khi chọn dòng)
            self.selected_row_panel = QWidget()
            self.selected_row_panel.setObjectName("selected_row_panel")
            self.selected_row_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            
            grid = QGridLayout(self.selected_row_panel)
            grid.setContentsMargins(12, 10, 12, 10)
            grid.setHorizontalSpacing(15)
            grid.setVerticalSpacing(8)
            
            self.selected_so_van_ban = QLabel()
            self.selected_ten_van_ban = QLabel()
            self.selected_ngay_ban_hanh = QLabel()
            self.selected_loai_van_ban = QLabel()
            self.selected_co_quan_phat_hanh = QLabel()
            self.selected_trich_yeu = QLabel()
            
            for lbl in [self.selected_so_van_ban, self.selected_ten_van_ban, self.selected_ngay_ban_hanh,
                        self.selected_loai_van_ban, self.selected_co_quan_phat_hanh, self.selected_trich_yeu]:
                lbl.setWordWrap(True)
                lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
                lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                
            self.set_selected_field(self.selected_so_van_ban, "Số văn bản", "-")
            self.set_selected_field(self.selected_ten_van_ban, "Tên văn bản", "-")
            self.set_selected_field(self.selected_ngay_ban_hanh, "Ngày phát hành", "-")
            self.set_selected_field(self.selected_loai_van_ban, "Loại văn bản", "-")
            self.set_selected_field(self.selected_co_quan_phat_hanh, "Cơ quan phát hành", "-")
            self.set_selected_field(self.selected_trich_yeu, "Trích yếu", "-")
            
            grid.addWidget(self.selected_so_van_ban, 0, 0)
            grid.addWidget(self.selected_ten_van_ban, 0, 1)
            grid.addWidget(self.selected_ngay_ban_hanh, 0, 2)
            grid.addWidget(self.selected_loai_van_ban, 0, 3)
            
            grid.addWidget(self.selected_co_quan_phat_hanh, 1, 0)
            grid.addWidget(self.selected_trich_yeu, 1, 1, 1, 3)
            
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 3)
            grid.setColumnStretch(2, 1)
            grid.setColumnStretch(3, 1)

            # 2. Table Widget
            self.table = QTableWidget(0, len(VISIBLE_FIELDS))
            self.table.setHorizontalHeaderLabels([FIELD_LABELS[field] for field in VISIBLE_FIELDS])
            self.table.cellDoubleClicked.connect(self.open_original_file)
            self.table.itemSelectionChanged.connect(self.update_selected_row_labels)
            self.table_corner_label = QLabel("TT", self.table)
            self.table_corner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table_corner_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.table_corner_label.setStyleSheet("background-color: #172a5a; color: #93c5fd; font-weight: bold; border-bottom: 2px solid #1e3a8a; border-right: 1px solid #1e3a8a;")
            
            # Setup columns Stretch/Interactive layout
            header = self.table.horizontalHeader()
            col_modes = {
                "so_van_ban": (QHeaderView.ResizeMode.Interactive, 120),
                "ten_van_ban": (QHeaderView.ResizeMode.Stretch, 300),
                "co_quan_phat_hanh": (QHeaderView.ResizeMode.Interactive, 150),
                "ngay_ban_hanh": (QHeaderView.ResizeMode.Interactive, 100),
                "loai_van_ban": (QHeaderView.ResizeMode.Interactive, 120),
                "trich_yeu": (QHeaderView.ResizeMode.Stretch, 400),
            }
            for i, field in enumerate(VISIBLE_FIELDS):
                mode, size = col_modes.get(field, (QHeaderView.ResizeMode.Interactive, 100))
                header.setSectionResizeMode(i, mode)
                if mode == QHeaderView.ResizeMode.Interactive:
                    self.table.setColumnWidth(i, size)

            # 3. Bottom Original Document Path Controls
            self.path_input = QLineEdit()
            self.path_input.setReadOnly(True)
            self.path_input.setPlaceholderText("Đường dẫn thư mục tài liệu gốc...")
            
            self.browse_btn = QPushButton("Browse...")
            self.browse_btn.clicked.connect(self.choose_folder)
            
            self.loading_circle = CircularProgressIndicator()
            
            self.scan_btn = QPushButton("Quét")
            self.scan_btn.setObjectName("scan_btn")
            self.scan_btn.clicked.connect(self.run_scan_action)
            
            self.export_btn = QPushButton("Xuất CSV")
            self.export_btn.clicked.connect(self.export_current_csv)

            path_layout = QHBoxLayout()
            path_layout.addWidget(self.path_input, stretch=1)
            path_layout.addWidget(self.browse_btn)
            path_layout.addWidget(self.loading_circle)
            path_layout.addWidget(self.scan_btn)
            path_layout.addWidget(self.export_btn)

            self.status = QLabel("Chọn thư mục và nhấn Quét")
            self.status.setObjectName("status_lbl")

            bottom_row_layout = QHBoxLayout()
            bottom_row_layout.addWidget(self.status)
            bottom_row_layout.addStretch()
            bottom_row_layout.addWidget(self.author_label)

            left = QWidget()
            left_layout = QVBoxLayout()
            left_layout.addLayout(header_layout)
            left_layout.addWidget(self.selected_row_panel)
            left_layout.addWidget(self.table)
            left_layout.addLayout(path_layout)
            left_layout.addLayout(bottom_row_layout)
            left.setLayout(left_layout)

            # 4. Chat Area Layout
            chat_header = QHBoxLayout()
            self.chat_scope = QComboBox()
            self.chat_scope.addItems(["Tài liệu đang chọn", "Tất cả tài liệu đã quét"])
            
            self.history_btn = QPushButton("🕒")
            self.history_btn.setObjectName("history_btn")
            self.history_btn.setToolTip("Lịch sử chat (3 phiên gần nhất)")
            self.history_btn.clicked.connect(self.show_history_menu)
            
            self.settings_btn = QPushButton("⚙️")
            self.settings_btn.setObjectName("settings_btn")
            self.settings_btn.setToolTip("Cài đặt LLM")
            self.settings_btn.clicked.connect(self.open_settings)
            
            chat_header.addWidget(self.chat_scope, stretch=1)
            chat_header.addWidget(self.history_btn)
            chat_header.addWidget(self.settings_btn)

            self.chat_history = QTextEdit()
            self.chat_history.setReadOnly(True)
            
            self.chat_input = QLineEdit()
            self.chat_input.setPlaceholderText("Nhập câu hỏi về tài liệu...")
            self.chat_input.returnPressed.connect(self.ask_chat)
            
            self.chat_send = QPushButton("➤")
            self.chat_send.setObjectName("chat_send")
            self.chat_send.clicked.connect(self.ask_chat)
            
            chat_input_row = QHBoxLayout()
            chat_input_row.addWidget(self.chat_input)
            chat_input_row.addWidget(self.chat_send)
            
            chat_panel = QWidget()
            chat_layout = QVBoxLayout()
            chat_layout.addWidget(QLabel("Chat với tài liệu"))
            chat_layout.addLayout(chat_header)
            chat_layout.addWidget(self.chat_history)
            chat_layout.addLayout(chat_input_row)
            chat_panel.setLayout(chat_layout)

            # Splitter between panels
            splitter = QSplitter(Qt.Orientation.Horizontal)
            splitter.addWidget(left)
            splitter.addWidget(chat_panel)
            splitter.setSizes([850, 450])

            layout = QVBoxLayout()
            layout.addWidget(splitter)
            root = QWidget()
            root.setLayout(layout)
            self.setCentralWidget(root)
            self.resize(1400, 800)
            self._restore_selected_folder()
            self.folder_watch_timer = QTimer(self)
            self.folder_watch_timer.timeout.connect(self.refresh_scan_button_state)
            self.folder_watch_timer.start(2000)
            self.load_rows(self.current_scan_folder)
            self.refresh_scan_button_state()

            # Apply gorgeous custom dark style sheet
            self.setStyleSheet(DARK_STYLE)

        def _restore_selected_folder(self) -> None:
            folder = _load_selected_folder()
            if folder is None:
                return
            self.current_scan_folder = folder
            self.path_input.setText(str(folder).replace("\\", "/"))
            self.synced_folder_signature = _folder_signature(folder)
            self.scan_btn.setText("C?p nh?t")
            self.status.setText(f"Da khoi phuc thu muc: {folder}")

        def choose_folder(self) -> None:
            folder = QFileDialog.getExistingDirectory(self, "Chon thu muc van ban")
            if folder:
                self.path_input.setText(folder.replace("\\", "/"))
                self.current_scan_folder = Path(folder)
                _save_selected_folder(self.current_scan_folder)
                self.synced_folder_signature = ()
                self.scan_btn.setText("Quét")
                self.scan_btn.setEnabled(True)
                self.status.setText(f"Da chon: {folder}")
                self.load_rows(self.current_scan_folder)

        def run_scan_action(self) -> None:
            if not self.current_scan_folder:
                self.status.setText("Vui long chon thu muc truoc khi quet!")
                return
            self._start_scan(self.current_scan_folder, Path("output/export.csv"))

        def refresh_scan_button_state(self) -> None:
            if self.scan_thread is not None:
                return
            if self.current_scan_folder is None:
                self.scan_btn.setText("Quét")
                self.scan_btn.setEnabled(False)
                return
            current_signature = _folder_signature(self.current_scan_folder)
            changed = current_signature != self.synced_folder_signature
            if self.synced_folder_signature:
                self.scan_btn.setText("Cập nhật")
            self.scan_btn.setEnabled(changed)

        def _start_scan(self, folder: Path, csv_path: Path) -> None:
            self.browse_btn.setEnabled(False)
            self.scan_btn.setEnabled(False)
            self.export_btn.setEnabled(False)
            self.loading_circle.set_value(0)
            self.loading_circle.start_spinning()
            self.status.setText(f"Đang chuẩn bị quét: {folder}")
            self.scan_thread = QThread(self)
            self.scan_worker = ScanWorker(folder, self.db_path, csv_path)
            self.scan_worker.moveToThread(self.scan_thread)
            self.scan_thread.started.connect(self.scan_worker.run)
            self.scan_worker.progress.connect(self._update_scan_progress)
            self.scan_worker.finished.connect(self._finish_scan)
            self.scan_worker.failed.connect(self._fail_scan)
            self.scan_worker.finished.connect(self.scan_thread.quit)
            self.scan_worker.failed.connect(self.scan_thread.quit)
            self.scan_thread.finished.connect(self.scan_worker.deleteLater)
            self.scan_thread.finished.connect(self.scan_thread.deleteLater)
            self.scan_thread.finished.connect(self._clear_scan_worker)
            self.scan_thread.start()

        def _update_scan_progress(self, current: int, total: int, file_name: str, action: str = "Đang xử lý") -> None:
            if total <= 0:
                self.loading_circle.set_value(0)
                self.status.setText(_progress_text(current, total, action=action))
                return
            percent = round(current / total * 100)
            self.loading_circle.set_value(percent)
            self.status.setText(_progress_text(current, total, file_name or None, action))

        def _finish_scan(self, row_count: int, deleted_count: int, review_count: int, csv_path: str) -> None:
            self.loading_circle.set_value(100)
            self.synced_folder_signature = _folder_signature(self.current_scan_folder)
            self.status.setText(f"Da dong bo {row_count} file moi/doi; xoa {deleted_count} file. CSV: {csv_path}")
            self.browse_btn.setEnabled(True)
            self.scan_btn.setText("Cập nhật")
            self.scan_btn.setEnabled(False)
            self.export_btn.setEnabled(True)
            self.load_rows(self.current_scan_folder, update_status=False)

        def _fail_scan(self, message: str) -> None:
            self.loading_circle.set_value(0)
            self.status.setText(f"Quet that bai: {message}")
            self.browse_btn.setEnabled(True)
            self.refresh_scan_button_state()
            self.export_btn.setEnabled(True)

        def _clear_scan_worker(self) -> None:
            self.scan_thread = None
            self.scan_worker = None

        def export_current_csv(self) -> None:
            path, _ = QFileDialog.getSaveFileName(self, "Luu CSV", "export.csv", "CSV (*.csv)")
            if path:
                export_csv(self.db_path, Path(path))
                self.status.setText(f"Đã xuất {path}")

        def load_rows(self, folder: Path | None = None, update_status: bool = True) -> None:
            self.table.setSortingEnabled(False)
            self.all_rows = _load_document_rows(self.db_path, folder)
            if self.current_scan_folder is None:
                inferred_folder = _infer_folder_from_rows(self.all_rows)
                if inferred_folder is not None:
                    self.current_scan_folder = inferred_folder
                    self.path_input.setText(str(inferred_folder).replace("\\", "/"))
                    _save_selected_folder(inferred_folder)
                    self.all_rows = _load_document_rows(self.db_path, inferred_folder)
            self.apply_search(update_status=update_status)

        def populate_table(self, rows: list[dict[str, object]]) -> None:
            self.table.setSortingEnabled(False)
            self.rows = rows
            self.table.setRowCount(len(self.rows))
            review_color = QColor(REVIEW_ROW_COLOR)
            for row_idx, row in enumerate(self.rows):
                row_needs_review = _is_review_value(row.get("needs_review"))
                for col_idx, field in enumerate(VISIBLE_FIELDS):
                    text = str(row.get(field) or "")
                    item = QTableWidgetItem(text)
                    item.setData(Qt.ItemDataRole.UserRole, row_idx)
                    if field == "so_van_ban":
                        item.setToolTip("Nhấp đúp chuột để mở file gốc")
                        item.setForeground(QColor("#38bdf8")) # Beautiful sea-blue color
                    elif text:
                        item.setToolTip(text)
                    if row_needs_review:
                        item.setBackground(review_color)
                    self.table.setItem(row_idx, col_idx, item)
            self._configure_table()
            self.update_selected_row_labels()

        def apply_search(self, update_status: bool = True) -> None:
            field = SEARCH_FIELDS[self.search_field.currentIndex()]
            query = self.search_input.text().strip()
            filtered_rows = _filter_rows(self.all_rows, field, query)
            self.populate_table(filtered_rows)
            if update_status:
                if query:
                    self.status.setText(f"Tìm thấy {len(filtered_rows)}/{len(self.all_rows)} file.")
                else:
                    self.status.setText(_status_text(len(filtered_rows), "Đã tải"))

        def open_original_file(self, row_index: int, _column: int) -> None:
            source_index = self.source_row_index_for_table_row(row_index)
            if source_index is None:
                return
            uri = _open_path_from_row(self.rows[source_index])
            if not uri or not QDesktopServices.openUrl(QUrl(uri)):
                self.status.setText("Không mở được file gốc")

        def selected_row_index(self) -> int | None:
            indexes = self.table.selectionModel().selectedRows()
            return indexes[0].row() if indexes else None

        def source_row_index_for_table_row(self, table_row: int) -> int | None:
            if table_row < 0:
                return None
            item = self.table.item(table_row, 0)
            if item is None:
                return None
            source_index = item.data(Qt.ItemDataRole.UserRole)
            return source_index if isinstance(source_index, int) and 0 <= source_index < len(self.rows) else None

        def selected_source_row_index(self) -> int | None:
            row_idx = self.selected_row_index()
            return self.source_row_index_for_table_row(row_idx) if row_idx is not None else None

        def set_selected_field(self, label_obj: QLabel, field_name: str, value: object) -> None:
            val_str = str(value or "").strip() or "-"
            label_obj.setText(f"<font color='#38bdf8'><b>{field_name}:</b></font> {val_str}")

        def update_selected_row_labels(self) -> None:
            row_idx = self.selected_source_row_index()
            if row_idx is not None and 0 <= row_idx < len(self.rows):
                row = self.rows[row_idx]
                self.set_selected_field(self.selected_so_van_ban, "Số văn bản", row.get("so_van_ban"))
                self.set_selected_field(self.selected_ten_van_ban, "Tên văn bản", row.get("ten_van_ban"))
                self.set_selected_field(self.selected_ngay_ban_hanh, "Ngày phát hành", row.get("ngay_ban_hanh"))
                self.set_selected_field(self.selected_loai_van_ban, "Loại văn bản", row.get("loai_van_ban"))
                self.set_selected_field(self.selected_co_quan_phat_hanh, "Cơ quan phát hành", row.get("co_quan_phat_hanh"))
                self.set_selected_field(self.selected_trich_yeu, "Trích yếu", row.get("trich_yeu"))
            else:
                self.set_selected_field(self.selected_so_van_ban, "Số văn bản", "-")
                self.set_selected_field(self.selected_ten_van_ban, "Tên văn bản", "-")
                self.set_selected_field(self.selected_ngay_ban_hanh, "Ngày phát hành", "-")
                self.set_selected_field(self.selected_loai_van_ban, "Loại văn bản", "-")
                self.set_selected_field(self.selected_co_quan_phat_hanh, "Cơ quan phát hành", "-")
                self.set_selected_field(self.selected_trich_yeu, "Trích yếu", "-")

        def resizeEvent(self, event) -> None:
            super().resizeEvent(event)
            self._sync_table_corner_label()
            w = self.width()
            title_size = max(18, min(24, int(w / 1400.0 * 20.0)))
            author_size = max(8, int(title_size / 3.0))
            
            font_title = self.app_title_label.font()
            font_title.setPointSize(title_size)
            self.app_title_label.setFont(font_title)
            
            font_author = self.author_label.font()
            font_author.setPointSize(author_size)
            self.author_label.setFont(font_author)

        def open_settings(self) -> None:
            dialog = SettingsDialog(self.llm_temperature, self.llm_max_tokens, self)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                self.llm_temperature, self.llm_max_tokens = dialog.get_values()
                self.chat_history.append(
                    f"<i>Cài đặt LLM đã cập nhật: Temp={self.llm_temperature}, Max Tokens={self.llm_max_tokens}</i>"
                )

        def show_history_menu(self) -> None:
            menu = QMenu(self)
            menu.setStyleSheet(DARK_STYLE)
            
            # Action: Start new session
            new_session_action = QAction("Bắt đầu phiên mới", self)
            new_session_action.triggered.connect(self.start_new_chat_session)
            menu.addAction(new_session_action)
            menu.addSeparator()

            if not self.chat_sessions:
                no_history = QAction("Không có lịch sử", self)
                no_history.setEnabled(False)
                menu.addAction(no_history)
            else:
                for idx, session in enumerate(self.chat_sessions):
                    preview = session["preview"]
                    if len(preview) > 30:
                        preview = preview[:27] + "..."
                    action = QAction(f"{idx+1}. {preview}", self)
                    action.triggered.connect(lambda checked=False, i=idx: self.load_chat_session(i))
                    menu.addAction(action)

            # Show menu under history button
            menu.exec(self.history_btn.mapToGlobal(self.history_btn.rect().bottomLeft()))

        def start_new_chat_session(self) -> None:
            # Save current session to history if there is any history content
            if self.current_session_questions:
                session_data = {
                    "preview": self.current_session_questions[0],
                    "html": self.chat_history.toHtml(),
                    "questions": list(self.current_session_questions)
                }
                # Prepend and slice to maximum 3 sessions
                self.chat_sessions = [session_data] + self.chat_sessions
                if len(self.chat_sessions) > 3:
                    self.chat_sessions = self.chat_sessions[:3]

            # Clear current state
            self.chat_history.clear()
            self.current_session_questions = []
            self.chat_history.append("<i>Bắt đầu phiên chat mới...</i>")

        def load_chat_session(self, index: int) -> None:
            if 0 <= index < len(self.chat_sessions):
                # Archive the current chat first
                current_html = self.chat_history.toHtml()
                current_questions = list(self.current_session_questions)

                # Load selected session
                session = self.chat_sessions[index]
                self.chat_history.setHtml(session["html"])
                self.current_session_questions = list(session["questions"])

                # Save current back to history slot
                if current_questions:
                    self.chat_sessions[index] = {
                        "preview": current_questions[0],
                        "html": current_html,
                        "questions": current_questions
                    }

        def ask_chat(self) -> None:
            question = self.chat_input.text().strip()
            if not question:
                return
            
            # Save query for session preview
            self.current_session_questions.append(question)
            
            selected_only = self.chat_scope.currentIndex() == 0
            selected_index = self.selected_source_row_index()
            context, sources = _build_chat_context(self.rows, question, selected_index, selected_only)
            self.chat_history.append(f"Bạn: {question}")
            self.chat_input.clear()
            self.chat_send.setEnabled(False)
            self.chat_history.append("Hệ thống: đang hỏi LLM...")
            self.chat_thread = QThread(self)
            self.chat_worker = ChatWorker(
                question, context, sources, self.llm_temperature, self.llm_max_tokens
            )
            self.chat_worker.moveToThread(self.chat_thread)
            self.chat_thread.started.connect(self.chat_worker.run)
            self.chat_worker.finished.connect(self._finish_chat)
            self.chat_worker.failed.connect(self._fail_chat)
            self.chat_worker.finished.connect(self.chat_thread.quit)
            self.chat_worker.failed.connect(self.chat_thread.quit)
            self.chat_thread.finished.connect(self.chat_worker.deleteLater)
            self.chat_thread.finished.connect(self.chat_thread.deleteLater)
            self.chat_thread.finished.connect(self._clear_chat_worker)
            self.chat_thread.start()

        def _finish_chat(self, answer: str, source_text: str) -> None:
            self.chat_history.append(f"LLM: {answer}\nNguồn: {source_text}")
            self.chat_send.setEnabled(True)

        def _fail_chat(self, message: str) -> None:
            self.chat_history.append(f"Hệ thống: {message}")
            self.chat_send.setEnabled(True)

        def _clear_chat_worker(self) -> None:
            self.chat_thread = None
            self.chat_worker = None

        def _sync_table_corner_label(self) -> None:
            if not hasattr(self, "table_corner_label"):
                return
            self.table_corner_label.setGeometry(0, 0, self.table.verticalHeader().width(), self.table.horizontalHeader().height())
            self.table_corner_label.raise_()

        def _configure_table(self) -> None:
            self.table.setSortingEnabled(True)
            self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
            self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
            self.table.setAlternatingRowColors(True)
            self.table.setWordWrap(False)
            self.table.setTextElideMode(Qt.TextElideMode.ElideRight)
            self._sync_table_corner_label()

    app = QApplication.instance() or QApplication([])
    window = Window()
    window.show()
    return app.exec()
