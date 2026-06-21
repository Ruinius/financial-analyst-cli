import re
import time

content = "Some prefix text\n## User Feedback\nSome suffix text" * 1000

def use_regex(c):
    return re.search(r"## User Feedback", c, re.IGNORECASE)

def use_find(c):
    idx = c.lower().find("## user feedback")
    if idx != -1:
        return idx
    return None

start = time.time()
for _ in range(1000):
    use_regex(content)
print(f"Regex: {time.time()-start:.6f}s")

start = time.time()
for _ in range(1000):
    use_find(content)
print(f"Find: {time.time()-start:.6f}s")
