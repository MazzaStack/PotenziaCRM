import pandas as pd
import re

df = pd.read_excel('base_temp.xlsx')
print(f"Total Rows: {len(df)}")
print(f"Columns: {df.columns.tolist()}")

potential_phones = {}

for col in df.columns:
    # Look for digits
    matches = df[df[col].astype(str).str.contains(r'\d{8,}', na=False)]
    if not matches.empty:
        potential_phones[col] = len(matches)

print("\nPotential Phone Columns:")
for col, count in potential_phones.items():
    print(f"- {col}: {count} matches")
    matching_rows = df[df[col].astype(str).str.contains(r'\d{8,}', na=False)]
    if not matching_rows.empty:
        print(f"  Example: {matching_rows[col].iloc[0]}")

# Look at some rows to see if we missed anything
print("\nFirst row full data:")
print(df.iloc[0].to_dict())
