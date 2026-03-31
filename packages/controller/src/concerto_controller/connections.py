"""Module to store shared state for WebSocket connections, such as the currently connected agents and dashboard clients.

This allows different parts of the application to access and manage WebSocket connections without circular imports.
"""

import uuid

from fastapi import WebSocket

# In-memory map of connected agents: agent_id → WebSocket
agent_connections: dict[uuid.UUID, WebSocket] = {}

# Connected dashboard clients
dashboard_connections: set[WebSocket] = set()
