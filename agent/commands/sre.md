---
description: Analyze log entry and provide structured Root Cause Analysis (RCA)
agent: sre-orchestrator
subtask: false
---

Analyze the following log entry and provide a structured Root Cause Analysis (RCA).

The log data contains:
- Timestamp (ISO format)
- Log level (ERROR, WARNING, INFO, DEBUG, etc.)
- Service name
- Log message
- Optional trace_id and metadata

Invoke the @sre-analyst agent to analyze this log, then invoke @rca-formatter to generate the structured JSON output. Return only the final JSON.
