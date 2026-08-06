from coding_agent_harness.feedback.pytest_parser import ParsedTestResult
from coding_agent_harness.security.canonical import canonical_sha256


def state_fingerprint(result: ParsedTestResult) -> str:
    return canonical_sha256({
        "phase": result.phase,
        "outcome": result.outcome,
        "node_ids": sorted(result.node_ids),
        "exception_type": result.exception_type,
        "summary": result.summary,
        "in_project_frames": sorted(result.in_project_frames),
    })
