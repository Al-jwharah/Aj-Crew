"""ajcrew-client — async Python client for the Aj Crew Gateway.

Usage::

    from ajcrew_client import AjCrewClient

    async with AjCrewClient(app_name="my-app") as mc:
        ok = await mc.ping()
        status = await mc.get_status()
        await mc.send_message("slot-1", "hello")
"""
from ajcrew_client.client import GATEWAY_CONFIG_KEYS, AjCrewClient
from ajcrew_client.errors import AjCrewError, ErrorCode
from ajcrew_client.ws_client import WsClient, WsEvent

__all__ = [
    "GATEWAY_CONFIG_KEYS",
    "AjCrewClient",
    "AjCrewError",
    "ErrorCode",
    "WsClient",
    "WsEvent",
]
