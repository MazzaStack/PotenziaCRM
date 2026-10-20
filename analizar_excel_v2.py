import pandas as pd
import re

try:
    df = pd.read_excel('base_temp.xlsx')
    print(f"Total Rows: {len(df)}")
    print(f"Columns: {df.columns.tolist()}")

    potential_phones = {}

    for col in df.columns:
        # Look for digits of length 8 or more
        s_col = df[col].astype(str)
        matches = df[s_col.str.contains(r'\d{8,}', na=False)]
        if not matches.empty:
            potential_phones[col] = len(matches)

    print("\nPotential Phone Columns:")
    for col, count in potential_phones.items():
        example_val = df[df[col].astype(str).str.contains(r'\d{8,}', na=False)][col].iloc[0]
        print(f"- {col}: {count} matches (Example: {example_val})")

    # If no phone found, list some random rows in full
    if not potential_phones:
        print("\nNo phone found in standard columns. Checking first 3 rows in detail:")
        for i in range(min(len(df), 3)):
            print(f"Row {i}: {df.iloc[i].to_dict()}")

except Exception as e:
    print(f"Error: {e}")
