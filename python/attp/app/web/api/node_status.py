from fastapi import APIRouter
from typing import Any


def get_api_router(attp_client: Any = None) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/nodes")
    async def get_nodes():
        if not attp_client:
            return {"agents": []}
        online_dids = set(attp_client.remote_agents.keys())
        agents = []
        for did, info in attp_client.registered_agents.items():
            agents.append(
                {
                    "did": info.get("did", did),
                    "name": info.get("name", ""),
                    "description": info.get("description", ""),
                    "ad_url": info.get("ad_url", ""),
                    "capabilities": info.get("capabilities", []),
                    "online": did in online_dids,
                }
            )
        return {"agents": agents}

    return router