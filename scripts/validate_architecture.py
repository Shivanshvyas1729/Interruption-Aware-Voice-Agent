import json
import argparse
import sys
from typing import Dict, List, Tuple

# Explicitly documented generic/ambiguous ports and their resolved directions
# based on docs/pivot-build-plan.md section 0 and PROJECT.md
EXPLICIT_GENERIC_PORTS: Dict[str, Dict[str, str]] = {
    "api-gateway": {
        "in": "INPUT",       # Web Client -> API Gateway (Auth req)
        "out": "OUTPUT",     # API Gateway -> Consent Service
        "left-2": "INPUT",   # Token Service -> API Gateway (Auth res)
        "right-2": "OUTPUT", # API Gateway -> Web Client (Auth res)
        "right-3": "OUTPUT"  # API Gateway -> Secrets Manager (internal API)
    },
    "app-state-store-db": {
        "in": "INPUT",       # Orchestrator -> Redis (State update)
        "out": "OUTPUT",     # Redis -> Orchestrator (State read)
        "left-2": "INPUT"    # Worker -> Redis (Job status update)
    },
    "task-execution-service": {
        "in": "INPUT",       # Redis -> Worker (Job queue)
        "left-2": "INPUT",   # External APIs -> Worker (Job res)
        "left-3": "INPUT",   # Legacy orchestrator -> worker (incorrect kill signal target)
        "right-3": "OUTPUT"  # Worker -> Redis (Status update)
    },
    "secrets-manager": {
        "in": "INPUT",       # API Gateway -> Secrets Manager
        "out": "OUTPUT"      # Secrets Manager -> Token Service
    },
    "token-service": {
        "left-2": "INPUT"    # Secrets Manager -> Token Service (keys)
    },
    "external-apis-integration": {
        "in-api": "INPUT"    # Worker -> External APIs
    }
}

class Violation:
    def __init__(self, edge_id: str, node_id: str, port_id: str, expected_direction: str, actual_direction: str, details: str):
        self.edge_id = edge_id
        self.node_id = node_id
        self.port_id = port_id
        self.expected_direction = expected_direction
        self.actual_direction = actual_direction
        self.details = details

    def __str__(self) -> str:
        return (
            f"Violation on Edge '{self.edge_id}': Node '{self.node_id}' Port '{self.port_id}' "
            f"expected {self.expected_direction}, but got {self.actual_direction} ({self.details})"
        )

def load_architecture(path: str) -> dict:
    """Loads the architecture JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def get_port_direction(node_id: str, port_id: str) -> str:
    """Resolves port direction to 'INPUT', 'OUTPUT', or 'AMBIGUOUS'."""
    if port_id.startswith("in-"):
        return "INPUT"
    if port_id.startswith("out-"):
        return "OUTPUT"
    
    # Check explicitly allowed/documented generic ports
    if node_id in EXPLICIT_GENERIC_PORTS and port_id in EXPLICIT_GENERIC_PORTS[node_id]:
        return EXPLICIT_GENERIC_PORTS[node_id][port_id]
        
    return "AMBIGUOUS"

def validate(architecture: dict) -> List[Violation]:
    """Validates port directions for all edges in the architecture graph."""
    violations: List[Violation] = []
    
    edges = architecture.get("edges", [])
    for edge in edges:
        edge_id = edge.get("id", "unnamed-edge")
        source = edge.get("source", {})
        target = edge.get("target", {})
        
        src_node = source.get("nodeId")
        src_port = source.get("portId")
        tgt_node = target.get("nodeId")
        tgt_port = target.get("portId")
        
        if not (src_node and src_port and tgt_node and tgt_port):
            violations.append(
                Violation(edge_id, "", "", "", "", "Malformed edge structure (missing nodeId or portId)")
            )
            continue
            
        # Validate Source (must be OUTPUT)
        src_dir = get_port_direction(src_node, src_port)
        if src_dir != "OUTPUT":
            violations.append(
                Violation(
                    edge_id, src_node, src_port, "OUTPUT", src_dir,
                    f"Edge source must be an output port. Node label: {src_node}"
                )
            )
            
        # Validate Target (must be INPUT)
        tgt_dir = get_port_direction(tgt_node, tgt_port)
        if tgt_dir != "INPUT":
            violations.append(
                Violation(
                    edge_id, tgt_node, tgt_port, "INPUT", tgt_dir,
                    f"Edge target must be an input port. Node label: {tgt_node}"
                )
            )
            
    return violations

def main():
    parser = argparse.ArgumentParser(description="Validate architecture port direction correctness.")
    parser.add_argument("path", help="Path to architecture JSON file")
    args = parser.parse_args()
    
    try:
        arch = load_architecture(args.path)
        violations = validate(arch)
        
        edges = arch.get("edges", [])
        print(f"Total Edges Scanned: {len(edges)}")
        
        if violations:
            print(f"[FAIL] Found {len(violations)} port direction violations:")
            for v in violations:
                print(f"  - {v}")
            sys.exit(1)
        else:
            print("[PASS] Architecture validation successful. No port direction violations found.")
            sys.exit(0)
            
    except Exception as e:
        print(f"Error loading or validating architecture: {e}")
        sys.exit(2)

if __name__ == "__main__":
    main()
