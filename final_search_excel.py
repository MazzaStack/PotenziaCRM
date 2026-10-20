import openpyxl
import re

wb = openpyxl.load_workbook('base_temp.xlsx', data_only=True)
sheet = wb.active

found = False
for r_idx, row in enumerate(sheet.iter_rows(values_only=True), 1):
    for c_idx, val in enumerate(row, 1):
        s_val = str(val) if val is not None else ""
        # Look for 8+ digits anywhere
        if re.search(r'\d{8,}', s_val):
            print(f"MATCH! Cell {openpyxl.utils.get_column_letter(c_idx)}{r_idx}: {s_val}")
            found = True
    if r_idx > 1000: break

if not found:
    print("No numbers with 8+ digits found in the first 1000 rows.")

wb.close()
