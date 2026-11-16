"""Editable table of the rock or explosive database (Rock Properties / Explosives tabs)."""
from __future__ import annotations

import csv

from PySide6 import QtCore as C
from PySide6 import QtGui as G
from PySide6 import QtWidgets as W

from .. import db

HEADERS = {
    "name": "Name", "name_it": "Name (Italian)", "density_t_m3": "Density (t/m3)", "ucs_mpa": "UCS (MPa)",
    "shear_mpa": "Shear strength (MPa)", "tensile_mpa": "Tensile strength (MPa)", "vp_ms": "Vp (m/s)",
    "frag_energy_kj_m2": "Fragmentation energy (kJ/m2)", "c_langefors": "Langefors c (kg/m3)",
    "rock_factor_A": "Rock factor A", "youngs_gpa": "Young's modulus (GPa)", "source": "Source",
    "notes": "Notes", "density_kg_dm3": "Density (kg/dm3)", "energy_mj_kg": "Energy (MJ/kg)",
    "vod_ms": "VOD (m/s)", "rws_anfo": "RWS (ANFO = 100)", "det_pressure_gpa": "Detonation pressure (GPa)",
}
COLORS = {"user": "#e3f4e1", "modified": "#fff3cd", "bad": "#f8d0d0"}


class DataTab(W.QWidget):
    changed = C.Signal()

    def __init__(self, kind: str, intro: str):
        super().__init__()
        self.kind = kind
        self.noun = kind[:-1]
        self._loading = False
        self.table = W.QTableWidget()
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(W.QAbstractItemView.SelectRows)
        self.table.itemChanged.connect(self._on_item_changed)
        self.status = W.QLabel()
        lay = W.QVBoxLayout(self)
        info = W.QLabel(intro + "  Green rows = added by you, yellow = modified built-in values. "
                        "Edits are saved automatically on this computer and stored in every saved project.")
        info.setWordWrap(True)
        lay.addWidget(info)
        lay.addWidget(self.table, 1)
        bar = W.QHBoxLayout()
        for text, fn in [(f"Add {self.noun}", self.add_row), ("Delete / restore selected", self.delete_selected),
                         ("Add parameter...", self.add_column), ("Import CSV...", self.import_csv),
                         ("Export CSV...", self.export_csv), ("Reset to original values", self.reset)]:
            b = W.QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            bar.addWidget(b)
        lay.addLayout(bar)
        lay.addWidget(self.status)
        from . import tips
        tips.by_text(self, {
            f"Add {self.noun}": "Adds a new row at the end of the table. Fill in the values you know; empty cells are treated as missing.",
            "Delete / restore selected": "Rows you added are deleted; for a built-in row the original values are restored.",
            "Add parameter...": "Adds a column of your own (any name) to store an extra property.",
            "Import CSV...": "Adds or updates rows from a CSV file with the same column names.",
            "Export CSV...": "Saves the table (built-in and your own rows) as a CSV file.",
            "Reset to original values": "Removes all your changes and returns to the shipped database."})
        self.table.setToolTip("Click a cell to edit it. Changes are saved automatically on this computer; only new or modified rows are stored.")
        self.reload()

    # ------------------------------------------------------------------ table <-> rows
    def reload(self):
        rows = db.effective_rows(self.kind)
        self.cols = db.columns(self.kind, rows)
        self._fill(rows)

    def _fill(self, rows):
        self._loading = True
        self.table.clear()
        self.table.setRowCount(len(rows))
        self.table.setColumnCount(len(self.cols))
        for j, c in enumerate(self.cols):
            h = W.QTableWidgetItem(HEADERS.get(c, c))
            h.setToolTip(f"column '{c}'" + ("" if c in HEADERS else " (custom parameter, not used by the calculations)"))
            self.table.setHorizontalHeaderItem(j, h)
        builtin = {r["name"] for r in db.builtin_rows(self.kind)}
        for i, r in enumerate(rows):
            for j, c in enumerate(self.cols):
                it = W.QTableWidgetItem(r.get(c, ""))
                if c == "name" and r["name"] in builtin:
                    it.setFlags(it.flags() & ~C.Qt.ItemIsEditable)       # a built-in name is the key
                self.table.setItem(i, j, it)
            self._colour_row(i)
        self.table.resizeColumnsToContents()
        self._loading = False
        self._update_status()

    def rows(self) -> list[dict]:
        out = []
        for i in range(self.table.rowCount()):
            out.append({c: (self.table.item(i, j).text() if self.table.item(i, j) else "")
                        for j, c in enumerate(self.cols)})
        return out

    def _invalid(self, row: dict) -> list[str]:
        bad = [k for k in db.REQUIRED[self.kind] if not (row.get(k) or "").strip()]
        for k in db.NUMERIC[self.kind]:
            v = (row.get(k) or "").strip()
            if v:
                try:
                    float(v)
                except ValueError:
                    bad.append(k)
        return bad

    def _colour_row(self, i: int):
        row = {c: (self.table.item(i, j).text() if self.table.item(i, j) else "") for j, c in enumerate(self.cols)}
        status = db.row_status(self.kind, row) if row["name"].strip() else "user"
        bad = self._invalid(row)
        for j, c in enumerate(self.cols):
            it = self.table.item(i, j)
            if it is None:
                continue
            col = COLORS["bad"] if c in bad else COLORS.get(status)
            it.setBackground(G.QBrush(G.QColor(col)) if col else G.QBrush())
            it.setForeground(G.QBrush(G.QColor("#222222")))
            it.setToolTip("missing or not a number: this row is ignored by the calculations" if c in bad else "")

    def _update_status(self):
        rows = self.rows()
        bad = [r["name"] for r in rows if self._invalid(r)]
        n_user = sum(1 for r in rows if r["name"].strip() and db.row_status(self.kind, r) != "builtin")
        msg = f"{len(rows)} {self.kind}, {n_user} added/modified by you"
        if bad:
            msg += f"  |  {len(bad)} with missing or invalid values (ignored): " + ", ".join(bad[:6])
        self.status.setText(msg)

    # ------------------------------------------------------------------ persistence
    def _persist(self):
        db.save_user_rows(self.kind, self.rows())
        self._update_status()
        self.changed.emit()

    def _on_item_changed(self, item):
        if self._loading:
            return
        i = item.row()
        if self.cols[item.column()] == "name":
            names = [self.table.item(k, item.column()).text().strip() for k in range(self.table.rowCount()) if k != i]
            if item.text().strip() in names or not item.text().strip():
                W.QMessageBox.warning(self, "Name", "Every item needs a unique, non-empty name.")
                self._loading = True
                item.setText(getattr(item, "_old", "") or self._unique_name(f"New {self.noun}"))
                self._loading = False
        self._colour_row(i)
        self._persist()

    def _unique_name(self, base: str) -> str:
        names = {r["name"] for r in self.rows()}
        k, n = 1, base
        while n in names:
            k += 1
            n = f"{base} {k}"
        return n

    # ------------------------------------------------------------------ buttons
    def add_row(self, name: str | None = None):
        rows = self.rows() + [{c: "" for c in self.cols} | {"name": name or self._unique_name(f"New {self.noun}"),
                                                                "source": "user"}]
        self._fill(rows)
        self._persist()
        self.table.selectRow(len(rows) - 1)
        self.table.scrollToBottom()

    def delete_selected(self):
        sel = sorted({ix.row() for ix in self.table.selectionModel().selectedRows()}, reverse=True)
        if not sel:
            return
        base = {r["name"]: r for r in db.builtin_rows(self.kind)}
        rows = self.rows()
        for i in sel:
            n = rows[i]["name"]
            if n in base:
                rows[i] = dict(base[n])            # built-in item: restore the original values
            else:
                del rows[i]                        # item added by the user: remove
        self._fill(rows)
        self._persist()

    def add_column(self, name: str | None = None):
        if name is None:
            name, ok = W.QInputDialog.getText(self, "New parameter", "Parameter name (e.g. porosity_pct):")
            if not ok:
                return
        name = name.strip().replace(",", "_")
        if not name or name in self.cols:
            W.QMessageBox.warning(self, "Parameter", "Give a new, non-empty parameter name.")
            return
        rows = self.rows()
        self.cols.append(name)
        for r in rows:
            r[name] = ""
        self._fill(rows)
        self._persist()

    def reset(self, confirm: bool = True):
        if confirm and W.QMessageBox.question(
                self, "Reset", f"Delete all your {self.kind} changes and go back to the original database?") \
                != W.QMessageBox.Yes:
            return
        db.reset_user_rows(self.kind)
        self.reload()
        self.changed.emit()

    def import_csv(self, path: str | None = None):
        if path is None:
            path, _ = W.QFileDialog.getOpenFileName(self, "Import CSV", "", "CSV (*.csv)")
        if not path:
            return
        with open(path, newline="", encoding="utf-8-sig") as fh:
            rows = list(csv.DictReader(fh))
        msgs = db.import_rows(self.kind, rows)
        self.reload()
        self.changed.emit()
        W.QMessageBox.information(self, "Import", "\n".join(msgs) or "Nothing new in the file.")

    def export_csv(self, path: str | None = None):
        if path is None:
            path, _ = W.QFileDialog.getSaveFileName(self, "Export CSV", f"{self.kind}.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, self.cols)
            w.writeheader()
            w.writerows(self.rows())
