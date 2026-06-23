import json, pathlib
d = pathlib.Path(r"c:\Users\44263\Documents\xhl\skills\量化交易\AStockAgent\data\results")
for f in sorted(d.glob("300033*analysis.cache.json")):
    data = json.loads(f.read_text(encoding="utf-8"))
    td = data.get("trade_date", "?")
    rt = data.get("rating", "?")
    cf = data.get("confidence", 0)
    print(f"  {td}  rating={rt}  conf={cf:.0%}")
