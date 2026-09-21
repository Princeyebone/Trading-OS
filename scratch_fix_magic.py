import os

replacements = {
    "engine/gi2_candle_pullback.py": [
        ('comment="GI2-PULLBACK",', 'comment="GI2-PULLBACK",\n            magic=202621,')
    ],
    "engine/gi2_prelondon_long.py": [
        ('comment="GI2-PRELONDON-LONG",', 'comment="GI2-PRELONDON-LONG",\n            magic=202623,'),
        ('"magic": 20003,', '"magic": 202623,')
    ],
    "engine/gi2_silver.py": [
        ('comment=f"GI2-XAG-{tag}",', 'comment=f"GI2-XAG-{tag}",\n            magic=202624,'),
        ('"magic": 20004,', '"magic": 202624,')
    ],
    "engine/gi3_eurusd.py": [
        ('comment=f"GI3-EUSDI-{tag}",', 'comment=f"GI3-EUSDI-{tag}",\n            magic=202632,')
    ],
    "engine/gi3_gold.py": [
        ('comment=f"GI3-XAU-{tag}",', 'comment=f"GI3-XAU-{tag}",\n                magic=202631,')
    ],
    "engine/scalping_integration.py": [
        ('comment="XAUUSD-i1-v2",', 'comment="XAUUSD-i1-v2",\n            magic=202611,')
    ],
    "engine/eusdi1_core.py": [
        # Wait, this one already has magic=MAGIC_NUMBER, I just need to check if MAGIC_NUMBER = 202710
        ('MAGIC_NUMBER = 202100', 'MAGIC_NUMBER = 202710')
    ],
    "engine/xagi1_core.py": [
        ('magic=202600', 'magic=202701')
    ],
    "engine/xagi2_core.py": [
        ('magic=202602', 'magic=202702')
    ]
}

base_dir = "c:/Users/HP/OneDrive/Desktop/tb/backend"

for rel_path, reps in replacements.items():
    file_path = os.path.join(base_dir, rel_path)
    if not os.path.exists(file_path):
        print(f"Not found: {file_path}")
        continue
        
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    modified = content
    for old, new in reps:
        if old in modified:
            modified = modified.replace(old, new)
        else:
            print(f"Warning: Could not find target in {file_path}:\n'{old}'")
            
    if modified != content:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(modified)
        print(f"Updated {file_path}")
    else:
        print(f"No changes made to {file_path}")

print("Done.")
