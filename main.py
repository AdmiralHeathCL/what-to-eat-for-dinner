from server_dinner import mcp
import sys
import traceback

if __name__ == "__main__":
    try:
        print("[Starting MCP server…]", file=sys.stderr, flush=True)  # keep stdout clean for MCP
        mcp.run()
    except Exception:
        traceback.print_exc(file=sys.stderr, flush=True)
        raise