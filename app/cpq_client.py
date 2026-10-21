
import os
import ssl
import logging

import certifi
import httpx

from dotenv import load_dotenv


load_dotenv()

logger = logging.getLogger(__name__)


class CPQClient:

    CONFIGURE_PATH = (
        "/rest/v19/configsQuotes.instruments."
        "instruments/actions/_configure"
    )

    UPDATE_PATH = (
        "/rest/v19/configsQuotes.instruments."
        "instruments/actions/_update"
    )

    BULK_ADD_PATH = (
        "/rest/v19/config/actions/_bulkAddToTxn"
    )

    def __init__(self):

        self.base_url = os.getenv(
            "CPQ_BASE_URL",
            "https://dev2tfs5.bigmachines.com"
        ).rstrip("/")

        self.username = os.getenv("CPQ_USERNAME")
        self.password = os.getenv("CPQ_PASSWORD")
        self.ca_bundle = os.getenv("CPQ_CA_BUNDLE")

        if not self.base_url.startswith("https://"):
            raise ValueError(
                "CPQ_BASE_URL must use HTTPS"
            )

        if not self.username or not self.password:
            raise ValueError(
                "CPQ_USERNAME and CPQ_PASSWORD "
                "must be configured in .env"
            )

    def get_ssl_context(self):

        context = ssl.create_default_context(
            cafile=certifi.where()
        )

        if self.ca_bundle:
            context.load_verify_locations(
                cafile=self.ca_bundle
            )

        return context

    async def _post(
        self,
        endpoint: str,
        payload: dict
    ) -> dict:

        url = self.base_url + endpoint

        logger.info(
            "Calling Oracle CPQ endpoint: %s",
            endpoint
        )

        async with httpx.AsyncClient(
            auth=httpx.BasicAuth(
                self.username,
                self.password
            ),
            timeout=90.0,
            verify=False,
            follow_redirects=False
        ) as client:

            response = await client.post(
                url,
                json=payload,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json"
                }
            )

            response.raise_for_status()

            return response.json()

    async def configure(
        self,
        payload: dict
    ) -> dict:

        return await self._post(
            self.CONFIGURE_PATH,
            payload
        )

    async def update(
        self,
        payload: dict
    ) -> dict:

        return await self._post(
            self.UPDATE_PATH,
            payload
        )

    async def bulk_add(
        self,
        payload: dict
    ) -> dict:

        return await self._post(
            self.BULK_ADD_PATH,
            payload
        )
