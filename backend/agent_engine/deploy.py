#!/usr/bin/env python3
"""Stretch S1 — deploy RecoverAICopilot to Vertex AI Agent Engine with Memory Bank. NOT BUILT.

PRD: start only after M8 is deployed and the demo passes 3x. The backend already reads COPILOT_RUNTIME
(cloudrun|agent_engine); only `cloudrun` is implemented — the co-pilot runs in-process on Cloud Run via ADK.
To build S1: wrap app.agents.copilot's LlmAgent in vertexai.agent_engines (ADK app), deploy with the current
Agent Engine SDK, configure VertexAiSessionService + VertexAiMemoryBankService, and forward chat turns from
routers/cases.py when COPILOT_RUNTIME=agent_engine.
"""
import sys

if __name__ == "__main__":
    sys.exit("S1 (Agent Engine) is a stretch goal and is not implemented in this prototype.")
