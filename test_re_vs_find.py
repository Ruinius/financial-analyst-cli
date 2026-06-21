import re
import time

content = "Some text\n" * 1000 + "## User Feedback\nThis is feedback\n" + "More text\n" * 1000

def use_regex(c):
    return re.search(r"## User Feedback", c, re.IGNORECASE)

def use_find(c):
    # Using python's highly optimized Boyer-Moore native find
    idx = c.lower().find("## user feedback")
    return idx if idx != -1 else None

start = time.time()
for _ in range(1000):
    use_regex(content)
print(f"Regex: {time.time()-start:.6f}s")

start = time.time()
for _ in range(1000):
    use_find(content)
print(f"Find: {time.time()-start:.6f}s")
