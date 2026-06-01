import re

path = r'app\ui\main_window.py'
with open(path, encoding='utf-8') as f:
    content = f.read()

# target 1: remove layout.addWidget(controls) and clear blank before task_controls
old = "        form.addRow(action_row)\n        layout.addWidget(controls)\n\n        task_controls = QGroupBox"
new = "        form.addRow(action_row)\n\n        task_controls = QGroupBox"
assert old in content, "t1 missing"
content = content.replace(old, new, 1)

# target 2: replace layout.addWidget(task_controls) with grid + loosefruit
old2 = "        task_form.addRow(task_action_row)\n        layout.addWidget(task_controls)\n\n        self.duplicate_table = QTableWidget(0, 9)"
assert old2 in content, "t2 missing"
new2 = '''        task_form.addRow(task_action_row)

        loosefruit_controls = QGroupBox("Loosefruit duplicate DocID (_)")
        loosefruit_form = QFormLayout(loosefruit_controls)
        self.loosefruit_loc_code = QLineEdit("")
        self.loosefruit_loc_code.setPlaceholderText("Kosong = seluruh lokasi")
        self.loosefruit_acc_month = QSpinBox()
        self.loosefruit_acc_month.setRange(0, 12)
        self.loosefruit_acc_month.setValue(self.config.default_period_month)
        self.loosefruit_acc_year = QSpinBox()
        self.loosefruit_acc_year.setRange(0, 2100)
        self.loosefruit_acc_year.setValue(self.config.default_period_year)
        self.loosefruit_limit = QSpinBox()
        self.loosefruit_limit.setRange(1, 10000)
        self.loosefruit_limit.setValue(1000)
        self.fetch_loosefruit_duplicates_button = QPushButton("Fetch Loosefruit DocIDs")
        self.delete_loosefruit_button = QPushButton("Scan Selected (Dry Run)")
        self.delete_loosefruit_button.setEnabled(False)
        self.loosefruit_dry_run = QCheckBox("Dry run")
        self.loosefruit_dry_run.setChecked(True)
        self.loosefruit_status_label = QLabel("Belum dicek.")
        self.fetch_loosefruit_duplicates_button.clicked.connect(self.fetch_loosefruit_duplicate_targets)
        self.delete_loosefruit_button.clicked.connect(self.run_loosefruit_delete)
        self.loosefruit_dry_run.toggled.connect(self._sync_loosefruit_button_text)
        self._sync_loosefruit_button_text()
        loosefruit_action_row = QHBoxLayout()
        loosefruit_action_row.addWidget(self.fetch_loosefruit_duplicates_button)
        loosefruit_action_row.addWidget(self.delete_loosefruit_button)
        loosefruit_action_row.addWidget(self.loosefruit_dry_run)
        loosefruit_action_row.addWidget(self.loosefruit_status_label, 1)
        loosefruit_form.addRow("LocCode (kosong=all)", self.loosefruit_loc_code)
        loosefruit_form.addRow("Acc Month (0=all)", self.loosefruit_acc_month)
        loosefruit_form.addRow("Acc Year (0=all)", self.loosefruit_acc_year)
        loosefruit_form.addRow("Limit", self.loosefruit_limit)
        loosefruit_form.addRow(loosefruit_action_row)

        cleanup_grid = QGridLayout()
        cleanup_grid.setHorizontalSpacing(8)
        cleanup_grid.addWidget(controls, 0, 0)
        cleanup_grid.addWidget(task_controls, 0, 1)
        cleanup_grid.addWidget(loosefruit_controls, 1, 0, 1, 2)
        layout.addLayout(cleanup_grid)

        self.duplicate_table = QTableWidget(0, 9)'''
content = content.replace(old2, new2, 1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("OK")