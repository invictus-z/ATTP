from fastapi import APIRouter, Request
from loguru import logger
from typing import Any


def get_api_router(config_manager: Any = None) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/config")
    async def get_config():
        if not config_manager:
            return {"error": "ATTP is not enabled", "config": None}
        return {
            "config": config_manager.attp_config.model_dump(by_alias=True)
        }

    @router.put("/config")
    async def update_config(request: Request):
        if not config_manager:
            return {"error": "ATTP is not enabled"}
        try:
            partial = await request.json()
            updated = config_manager.update(partial)
            return {
                "success": True,
                "config": updated.model_dump(by_alias=True),
            }
        except Exception as e:
            logger.error(f"Error updating ATTP config: {e}")
            return {"success": False, "error": str(e)}

    return router