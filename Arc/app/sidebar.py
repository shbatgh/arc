"""Cell property sidebar panel."""

from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView


class SidebarPanel(QTableWidget):
    """Two-column property table showing selected cell info."""

    def __init__(self, parent=None):
        super().__init__(0, 2, parent)
        self.setHorizontalHeaderLabels(["Property", "Value"])
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)

    def update_properties(self, rows: list[tuple[str, str]]) -> None:
        """Set the property table rows from a list of (name, value) pairs."""
        self.setRowCount(len(rows))
        for i, (name, value) in enumerate(rows):
            self.setItem(i, 0, QTableWidgetItem(name))
            self.setItem(i, 1, QTableWidgetItem(str(value)))

    def clear_properties(self) -> None:
        self.setRowCount(0)
