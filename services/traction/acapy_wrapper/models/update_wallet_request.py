# coding: utf-8

from __future__ import annotations
from datetime import date, datetime  # noqa: F401

import re  # noqa: F401
from typing import Any, Dict, List, Optional  # noqa: F401

from pydantic import AnyUrl, BaseModel, EmailStr, validator  # noqa: F401


class UpdateWalletRequest(BaseModel):
    """NOTE: This class is auto generated by OpenAPI Generator (https://openapi-generator.tech).

    Do not edit the class manually.

    UpdateWalletRequest - a model defined in OpenAPI

        image_url: The image_url of this UpdateWalletRequest [Optional].
        label: The label of this UpdateWalletRequest [Optional].
        wallet_dispatch_type: The wallet_dispatch_type of this UpdateWalletRequest [Optional].
        wallet_webhook_urls: The wallet_webhook_urls of this UpdateWalletRequest [Optional].
    """

    image_url: Optional[str] = None
    label: Optional[str] = None
    wallet_dispatch_type: Optional[str] = None
    wallet_webhook_urls: Optional[List[str]] = None


UpdateWalletRequest.update_forward_refs()