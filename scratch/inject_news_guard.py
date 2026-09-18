import re
import os

def inject():
    filepath = r"c:\Users\HP\OneDrive\Desktop\tb\backend\engine\scheduler.py"
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
        
    # We want to find functions like `def run_xagi5_scalping_cycle():`
    # and right after `global DRY_RUN...` or `session = get_session()` add the news check.
    # The safest place is right after the docstring or first line of the function.
    
    # We will search for:
    # def run_[a-zA-Z0-9_]+scalping_cycle\(\):
    #     .*?
    #     global DRY_RUN.*?
    
    # Let's write a regex that matches the signature and injects code right after it.
    
    injection = """
    # --- NEWS GUARD ---
    is_blackout, label = is_news_blackout(15)
    if is_blackout:
        logger.info(f"[NEWS GUARD] Scalping paused due to: {label}")
        return
    # ------------------
"""

    def replacer(match):
        func_def = match.group(0)
        return func_def + injection

    pattern = re.compile(r'(def run_[a-zA-Z0-9_]+scalping_cycle\(\):\n(?:    """.*?"""\n)?(?:    global .*?\n)?)')
    new_content = pattern.sub(replacer, content)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
        
    print("Injection complete!")

if __name__ == "__main__":
    inject()
