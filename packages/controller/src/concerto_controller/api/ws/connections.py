import uuid

from fastapi import WebSocket

# In-memory map of connected agents: agent_id → WebSocket
agent_connections: dict[uuid.UUID, WebSocket] = {}

# Connected dashboard clients
dashboard_connections: set[WebSocket] = set()
