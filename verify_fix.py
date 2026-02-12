import sys
import os
sys.path.append(os.getcwd())
try:
    from arxivc import citation_service
    print("Import successful")
except ImportError as e:
    print(f"Import failed: {e}")
    sys.exit(1)

def test():
    print("Testing get_paper_graph with retry logic...")
    # Attention Is All You Need
    result = citation_service.get_paper_graph("1706.03762")
    nodes = result.get("nodes", [])
    edges = result.get("edges", [])
    print(f"Nodes: {len(nodes)}")
    print(f"Edges: {len(edges)}")
    
    if len(nodes) > 1:
        print("SUCCESS: Graph data retrieved.")
    else:
        print("FAILURE: Graph data empty.")

if __name__ == "__main__":
    test()
