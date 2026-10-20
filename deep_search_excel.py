import pandas as pd
import re

try:
    df = pd.read_excel('base_temp.xlsx')
    print(f"Total rows: {len(df)}")
    
    # Argentinian phone patterns
    # Mobile: 11, 15, or area codes (2xx, 3xx)
    # Looking for sequences of 8-12 digits
    
    found_any = False
    for r_idx, row in df.iterrows():
        for col in df.columns:
            val = str(row[col])
            # Match digits, potentially with spaces, hyphens, or plus
            # We want at least 8 digits
            digits = re.sub(r'\D', '', val)
            if len(digits) >= 8 and len(digits) <= 13:
                # Check if it looks like a phone (doesn't start with 000)
                if not digits.startswith('000'):
                    print(f"MATCH! Row {r_idx}, Col '{col}': {val} (Digits: {digits})")
                    found_any = True
        if r_idx > 200: # Scan more rows
            break
            
    if not found_any:
        print("No numbers 8-13 digits found in first 200 rows.")
        # Print a whole row to see what we're missing
        print("\nRow 50 full data:")
        print(df.iloc[50].to_dict())

except Exception as e:
    print(f"Error: {e}")
