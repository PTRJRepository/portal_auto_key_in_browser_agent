"""Modern UI themes and styles for Auto Key In Refactor."""
from __future__ import annotations


class AppTheme:
    """Modern theme system for the application."""

    # Color palette - Modern dark theme with accent colors
    PRIMARY = "#3b82f6"  # Blue
    PRIMARY_DARK = "#2563eb"
    PRIMARY_LIGHT = "#60a5fa"
    SUCCESS = "#22c55e"  # Green
    SUCCESS_DARK = "#16a34a"
    WARNING = "#f59e0b"  # Amber
    WARNING_DARK = "#d97706"
    ERROR = "#ef4444"  # Red
    ERROR_DARK = "#dc2626"
    INFO = "#06b6d4"  # Cyan
    
    # Background colors
    BG_PRIMARY = "#0f172a"  # Slate 900
    BG_SECONDARY = "#1e293b"  # Slate 800
    BG_TERTIARY = "#334155"  # Slate 700
    BG_CARD = "#1e293b"
    
    # Text colors
    TEXT_PRIMARY = "#f8fafc"  # Slate 50
    TEXT_SECONDARY = "#cbd5e1"  # Slate 300
    TEXT_MUTED = "#94a3b8"  # Slate 400
    TEXT_DISABLED = "#64748b"  # Slate 500
    
    # Border colors
    BORDER = "#334155"
    BORDER_HOVER = "#475569"
    BORDER_FOCUS = "#3b82f6"
    
    # Status indicator colors
    STATUS_SUCCESS = "#22c55e"
    STATUS_WARNING = "#f59e0b"
    STATUS_ERROR = "#ef4444"
    STATUS_INFO = "#06b6d4"
    STATUS_PENDING = "#8b5cf6"  # Purple
    STATUS_NEUTRAL = "#64748b"

    @classmethod
    def get_stylesheet(cls) -> str:
        """Generate complete application stylesheet."""
        return f"""
        /* Main Window */
        QMainWindow {{
            background-color: {cls.BG_PRIMARY};
        }}
        
        /* QWidget base */
        QWidget {{
            background-color: {cls.BG_PRIMARY};
            color: {cls.TEXT_PRIMARY};
            font-family: "Segoe UI", "Inter", system-ui, sans-serif;
            font-size: 13px;
        }}
        
        /* QTabWidget */
        QTabWidget::pane {{
            border: 1px solid {cls.BORDER};
            border-radius: 8px;
            background-color: {cls.BG_SECONDARY};
            padding: 12px;
        }}
        
        QTabBar::tab {{
            background-color: {cls.BG_TERTIARY};
            color: {cls.TEXT_SECONDARY};
            padding: 10px 20px;
            margin-right: 4px;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            font-weight: 500;
        }}
        
        QTabBar::tab:selected {{
            background-color: {cls.PRIMARY};
            color: {cls.TEXT_PRIMARY};
        }}
        
        QTabBar::tab:hover:!selected {{
            background-color: {cls.BORDER_HOVER};
            color: {cls.TEXT_PRIMARY};
        }}
        
        /* QGroupBox */
        QGroupBox {{
            background-color: {cls.BG_SECONDARY};
            border: 1px solid {cls.BORDER};
            border-radius: 8px;
            margin-top: 12px;
            padding-top: 12px;
            font-weight: 600;
        }}
        
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 8px;
            color: {cls.TEXT_PRIMARY};
        }}
        
        /* QPushButton */
        QPushButton {{
            background-color: {cls.BG_TERTIARY};
            color: {cls.TEXT_PRIMARY};
            border: 1px solid {cls.BORDER};
            border-radius: 6px;
            padding: 8px 16px;
            min-width: 80px;
            font-weight: 500;
        }}
        
        QPushButton:hover {{
            background-color: {cls.BORDER_HOVER};
            border-color: {cls.BORDER_HOVER};
        }}
        
        QPushButton:pressed {{
            background-color: {cls.BORDER};
        }}
        
        QPushButton:disabled {{
            background-color: {cls.BG_TERTIARY};
            color: {cls.TEXT_DISABLED};
            border-color: {cls.BORDER};
        }}
        
        QPushButton#primary {{
            background-color: {cls.PRIMARY};
            border-color: {cls.PRIMARY};
        }}
        
        QPushButton#primary:hover {{
            background-color: {cls.PRIMARY_DARK};
            border-color: {cls.PRIMARY_DARK};
        }}
        
        QPushButton#success {{
            background-color: {cls.SUCCESS};
            border-color: {cls.SUCCESS};
            color: {cls.BG_PRIMARY};
        }}
        
        QPushButton#success:hover {{
            background-color: {cls.SUCCESS_DARK};
            border-color: {cls.SUCCESS_DARK};
        }}
        
        QPushButton#warning {{
            background-color: {cls.WARNING};
            border-color: {cls.WARNING};
            color: {cls.BG_PRIMARY};
        }}
        
        QPushButton#danger {{
            background-color: {cls.ERROR};
            border-color: {cls.ERROR};
        }}
        
        QPushButton#danger:hover {{
            background-color: {cls.ERROR_DARK};
            border-color: {cls.ERROR_DARK};
        }}
        
        /* QLineEdit, QSpinBox, QComboBox, QTextEdit */
        QLineEdit, QSpinBox, QComboBox, QTextEdit {{
            background-color: {cls.BG_PRIMARY};
            color: {cls.TEXT_PRIMARY};
            border: 1px solid {cls.BORDER};
            border-radius: 6px;
            padding: 6px 10px;
            selection-background-color: {cls.PRIMARY};
        }}
        
        QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTextEdit:focus {{
            border-color: {cls.BORDER_FOCUS};
        }}
        
        QLineEdit:hover, QSpinBox:hover, QComboBox:hover, QTextEdit:hover {{
            border-color: {cls.BORDER_HOVER};
        }}
        
        QSpinBox::up-button, QSpinBox::down-button {{
            background-color: {cls.BG_TERTIARY};
            border: none;
            border-radius: 3px;
            margin: 2px;
        }}
        
        QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
            background-color: {cls.BORDER_HOVER};
        }}
        
        QComboBox::drop-down {{
            border: none;
            padding-right: 8px;
        }}
        
        QComboBox::down-arrow {{
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 5px solid {cls.TEXT_SECONDARY};
        }}
        
        QComboBox QAbstractItemView {{
            background-color: {cls.BG_SECONDARY};
            color: {cls.TEXT_PRIMARY};
            border: 1px solid {cls.BORDER};
            selection-background-color: {cls.PRIMARY};
        }}
        
        /* QCheckBox */
        QCheckBox {{
            spacing: 8px;
        }}
        
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border: 2px solid {cls.BORDER};
            border-radius: 4px;
            background-color: {cls.BG_PRIMARY};
        }}
        
        QCheckBox::indicator:checked {{
            background-color: {cls.PRIMARY};
            border-color: {cls.PRIMARY};
            image: url(data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNCIgaGVpZ2h0PSIxNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJub25lIiBzdHJva2U9IndoaXRlIiBzdHJva2Utd2lkdGg9IjMiPjxwb2x5bGluZSBwb2ludHM9IjIwIDYgOSAxNyA0IDEyIi8+PC9zdmc+);
        }}
        
        QCheckBox::indicator:hover {{
            border-color: {cls.BORDER_HOVER};
        }}
        
        /* QTableWidget */
        QTableWidget {{
            background-color: {cls.BG_SECONDARY};
            border: 1px solid {cls.BORDER};
            border-radius: 8px;
            gridline-color: {cls.BORDER};
            selection-background-color: {cls.PRIMARY};
            selection-color: {cls.TEXT_PRIMARY};
        }}
        
        QTableWidget::item {{
            padding: 8px;
            border-bottom: 1px solid {cls.BORDER};
        }}
        
        QTableWidget::item:selected {{
            background-color: {cls.PRIMARY};
        }}
        
        QHeaderView::section {{
            background-color: {cls.BG_TERTIARY};
            color: {cls.TEXT_PRIMARY};
            padding: 10px;
            border: none;
            border-bottom: 2px solid {cls.BORDER};
            font-weight: 600;
        }}
        
        QHeaderView::section:hover {{
            background-color: {cls.BORDER_HOVER};
        }}
        
        /* QScrollBar */
        QScrollBar:vertical {{
            background-color: {cls.BG_SECONDARY};
            width: 10px;
            border-radius: 5px;
        }}
        
        QScrollBar::handle:vertical {{
            background-color: {cls.BG_TERTIARY};
            border-radius: 5px;
            min-height: 20px;
        }}
        
        QScrollBar::handle:vertical:hover {{
            background-color: {cls.BORDER_HOVER};
        }}
        
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        
        QScrollBar:horizontal {{
            background-color: {cls.BG_SECONDARY};
            height: 10px;
            border-radius: 5px;
        }}
        
        QScrollBar::handle:horizontal {{
            background-color: {cls.BG_TERTIARY};
            border-radius: 5px;
            min-width: 20px;
        }}
        
        QScrollBar::handle:horizontal:hover {{
            background-color: {cls.BORDER_HOVER};
        }}
        
        /* QLabel */
        QLabel {{
            color: {cls.TEXT_PRIMARY};
        }}
        
        QLabel#title {{
            font-size: 24px;
            font-weight: 700;
            color: {cls.TEXT_PRIMARY};
        }}
        
        QLabel#subtitle {{
            font-size: 16px;
            font-weight: 500;
            color: {cls.TEXT_SECONDARY};
        }}
        
        QLabel#status-success {{
            color: {cls.SUCCESS};
            font-weight: 600;
        }}
        
        QLabel#status-warning {{
            color: {cls.WARNING};
            font-weight: 600;
        }}
        
        QLabel#status-error {{
            color: {cls.ERROR};
            font-weight: 600;
        }}
        
        QLabel#status-info {{
            color: {cls.INFO};
            font-weight: 600;
        }}
        
        QLabel#card-value {{
            font-size: 28px;
            font-weight: 700;
            color: {cls.TEXT_PRIMARY};
        }}
        
        QLabel#card-title {{
            font-size: 12px;
            font-weight: 500;
            color: {cls.TEXT_MUTED};
            text-transform: uppercase;
        }}
        
        /* QFormLayout row styling */
        QFormLayout {{
            spacing: 12px;
        }}
        
        /* QVBoxLayout, QHBoxLayout, QGridLayout - no direct styling */
        /* QTextEdit read-only (log output) */
        QTextEdit[readOnly="true"] {{
            background-color: {cls.BG_PRIMARY};
            border: 1px solid {cls.BORDER};
            border-radius: 6px;
            padding: 8px;
            font-family: "Consolas", "Monaco", "Courier New", monospace;
            font-size: 12px;
        }}
        
        /* Status bar */
        QStatusBar {{
            background-color: {cls.BG_SECONDARY};
            border-top: 1px solid {cls.BORDER};
        }}
        
        /* Menu bar */
        QMenuBar {{
            background-color: {cls.BG_SECONDARY};
            border-bottom: 1px solid {cls.BORDER};
        }}
        
        QMenuBar::item:selected {{
            background-color: {cls.PRIMARY};
        }}
        
        QMenu {{
            background-color: {cls.BG_SECONDARY};
            border: 1px solid {cls.BORDER};
        }}
        
        QMenu::item:selected {{
            background-color: {cls.PRIMARY};
        }}
        
        /* Tooltips */
        QToolTip {{
            background-color: {cls.BG_TERTIARY};
            color: {cls.TEXT_PRIMARY};
            border: 1px solid {cls.BORDER};
            border-radius: 4px;
            padding: 6px 10px;
        }}
        
        /* QProgressBar */
        QProgressBar {{
            border: none;
            border-radius: 4px;
            background-color: {cls.BG_TERTIARY};
            text-align: center;
            height: 8px;
        }}
        
        QProgressBar::chunk {{
            background-color: {cls.PRIMARY};
            border-radius: 4px;
        }}
        """

    @classmethod
    def get_status_style(cls, status: str) -> str:
        """Get style for a status label based on status type."""
        status = status.lower()
        if status in ("success", "match", "ok", "verified_match", "done", "completed"):
            return f"color: {cls.STATUS_SUCCESS}; font-weight: 600;"
        elif status in ("warning", "pending", "processing", "manual", "mismatch", "verified_mismatch"):
            return f"color: {cls.STATUS_WARNING}; font-weight: 600;"
        elif status in ("error", "fail", "failed", "miss", "missing", "verified_not_found", "verify_error"):
            return f"color: {cls.STATUS_ERROR}; font-weight: 600;"
        elif status in ("info", "unknown", "no remarks"):
            return f"color: {cls.STATUS_INFO}; font-weight: 600;"
        else:
            return f"color: {cls.STATUS_NEUTRAL};"

    @classmethod
    def get_card_stylesheet(cls, border_color: str | None = None) -> str:
        """Get stylesheet for a stat card."""
        border = border_color or cls.BORDER
        return f"""
            background-color: {cls.BG_SECONDARY};
            border: 1px solid {border};
            border-radius: 8px;
            padding: 16px;
        """
