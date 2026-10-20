
import re

with open("templates/index.html", "r", encoding="utf-8") as f:
    content = f.read()

scripts = re.findall(r"<script>(.*?)</script>", content, re.DOTALL)
with open("test.js", "w", encoding="utf-8") as f:
    f.write(scripts[0]) # There is only one main script block

