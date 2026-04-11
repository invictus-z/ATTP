import copy

from fastapi import APIRouter, Query, Request
from typing import Any

from attp_channel.logging import get_logger

logger = get_logger("Config")


def get_api_router(config_manager: Any = None, reload_callback: Any = None) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/config")
    async def get_config(refresh: bool = Query(False)):
        if not config_manager:
            return {"error": "ATTP is not enabled", "config": None}
        if refresh:
            config_manager.load()
        return {
            "config": config_manager.attp_config.model_dump(by_alias=True)
        }

    @router.put("/config")
    async def update_config(request: Request):
        """Save configuration to disk (no hot-reload). Use POST /config/reload to apply."""
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
            logger.error("Error updating ATTP config: {}", e)
            return {"success": False, "error": str(e)}

    @router.post("/config/reload")
    async def reload_config():
        """Re-read config from disk and trigger hot-reload of all components."""
        if not config_manager:
            return {"error": "ATTP is not enabled"}
        try:
            old_cfg = copy.deepcopy(config_manager.attp_config)
            config_manager.load()
            new_cfg = config_manager.attp_config

            if reload_callback is not None:
                await reload_callback(old_cfg, new_cfg)

            return {
                "success": True,
                "config": new_cfg.model_dump(by_alias=True),
            }
        except Exception as e:
            logger.error("Error reloading ATTP config: {}", e)
            return {"success": False, "error": str(e)}

    return router
