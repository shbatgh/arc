from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget, QTableWidget, QTableWidgetItem, QHeaderView


class Sidebar(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        title = QLabel("Sidebar")
        title.setObjectName("SidebarTitle")
        layout.addWidget(title)

        layout.addWidget(QLabel("Selection"))
        
        self.props_table = QTableWidget()
        self.props_table.setColumnCount(2)
        self.props_table.setHorizontalHeaderLabels(["Property", "Value"])
        self.props_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.props_table.verticalHeader().setVisible(False)
        layout.addWidget(self.props_table)

        layout.addStretch(1)

    def update_properties(self, data: dict[str, str | float | int]) -> None:
        self.props_table.setRowCount(len(data))
        for row, (key, value) in enumerate(data.items()):
            self.props_table.setItem(row, 0, QTableWidgetItem(str(key)))
            self.props_table.setItem(row, 1, QTableWidgetItem(str(value)))
