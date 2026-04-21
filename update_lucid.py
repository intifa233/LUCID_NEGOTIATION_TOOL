import re

with open('lucid.py', 'r') as f:
    lines = f.readlines()

with open('lucid.py', 'w') as f:
    for line in lines:
        if "offer_keywords =" in line and "'proposal'" not in line:
            line = line.replace("'propose',", "'propose', 'proposal',")
        if "numeric_pattern =" in line:
            line = "    numeric_pattern = r'\\$?\\d+(?:,\\d{3})*(?:\\.\\d{2})?%?'\n"
        f.write(line)
