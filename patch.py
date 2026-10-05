import sys

filepath = 'src/agents/modeler_agents/non_operating_agent.py'
with open(filepath, 'r') as f:
    content = f.read()

search = """    # Extract non-operating items from blackboard
    non_operating_assets = [
        item
        for item in report.financial_data.line_items
        if item.category in ("current_assets", "noncurrent_assets")
        and not item.operating
    ]
    non_operating_liabilities = [
        item
        for item in report.financial_data.line_items
        if item.category in ("current_liabilities", "noncurrent_liabilities")
        and not item.operating
    ]"""

replace = """    # Extract non-operating items from blackboard
    # ⚡ Bolt Optimization: Combine List Comprehensions into a Single Pass to avoid redundant O(N) traversal
    non_operating_assets = []
    non_operating_liabilities = []
    for item in report.financial_data.line_items:
        if not item.operating:
            if item.category in ("current_assets", "noncurrent_assets"):
                non_operating_assets.append(item)
            elif item.category in ("current_liabilities", "noncurrent_liabilities"):
                non_operating_liabilities.append(item)"""

if search in content:
    content = content.replace(search, replace)
    with open(filepath, 'w') as f:
        f.write(content)
    print("Patch applied successfully.")
else:
    print("Search string not found.")
    sys.exit(1)
