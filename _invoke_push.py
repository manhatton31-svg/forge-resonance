"""Load batch JSON and print MCP-ready arguments to stdout."""
import json
import sys

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "_call_mcp0.json"
    with open(path, encoding="utf-8") as f:
        args = json.load(f)
    sys.stdout.reconfigure(encoding="utf-8")
    json.dump(args, sys.stdout, ensure_ascii=False)

if __name__ == "__main__":
    main()