import openpyxl

wb = openpyxl.load_workbook('base_temp.xlsx', data_only=True)
sheet = wb.active

print("Reading first 10 rows completely (30 columns):")
for row in sheet.iter_rows(min_row=1, max_row=10, min_col=1, max_col=30):
    vals = [str(cell.value) if cell.value is not None else "-" for cell in row]
    print(" | ".join(vals))

wb.close()
