import logging
import requests

from sqlalchemy.ext.asyncio import AsyncSession

from api.api_client_utils import get_api_client
from api.core.config import settings
from api.db.repositories.tenant_issuers import TenantIssuersRepository
from api.db.repositories.tenant_workflows import TenantWorkflowsRepository
from api.db.models.tenant_issuer import TenantIssuerUpdate
from api.db.models.tenant_workflow import (
    TenantWorkflowRead,
    TenantWorkflowUpdate,
)
from api.endpoints.models.connections import (
    ConnectionStateType,
)
from api.endpoints.models.tenant_issuer import (
    PublicDIDStateType,
)
from api.endpoints.models.tenant_workflow import (
    TenantWorkflowStateType,
)
from api.endpoints.models.webhooks import (
    WebhookTopicType,
)
from api.services.connections import (
    receive_invitation,
)

from acapy_client.api.endorse_transaction_api import EndorseTransactionApi
from acapy_client.api.ledger_api import LedgerApi
from acapy_client.api.wallet_api import WalletApi
from acapy_client.model.did_create import DIDCreate


logger = logging.getLogger(__name__)

endorse_api = EndorseTransactionApi(api_client=get_api_client())
ledger_api = LedgerApi(api_client=get_api_client())
wallet_api = WalletApi(api_client=get_api_client())


class IssuerWorkflow:
    """Workflow to setup a tenant's Issuer configuration."""

    def __init__(self, db: AsyncSession, tenant_workflow: TenantWorkflowRead):
        """
        Initialize a new `IssuerWorkflow` instance.

        Args:
            session: The Askar profile session instance to use
        """
        self._db = db
        self._tenant_workflow = tenant_workflow
        self._issuer_repo = TenantIssuersRepository(db_session=db)
        self._workflow_repo = TenantWorkflowsRepository(db_session=db)

    @property
    def db(self) -> AsyncSession:
        """Accessor for db session instance."""
        return self._db

    @property
    def tenant_workflow(self) -> TenantWorkflowRead:
        """Accessor for tenant_workflow instance."""
        return self._tenant_workflow

    @property
    def issuer_repo(self) -> TenantIssuersRepository:
        """Accessor for issuer_repo instance."""
        return self._issuer_repo

    @property
    def workflow_repo(self) -> TenantWorkflowsRepository:
        """Accessor for workflow_repo instance."""
        return self._workflow_repo

    async def run_step(self, webhook_message: dict = None) -> TenantWorkflowRead:
        tenant_issuer = await self.issuer_repo.get_by_wallet_id(
            self.tenant_workflow.wallet_id
        )

        # if workflow is "pending" then we need to start it
        # called direct from the tenant admin api so the tenant is "in context"
        if self.tenant_workflow.workflow_state == TenantWorkflowStateType.pending:
            # update the workflow status as "active"
            update_workflow = TenantWorkflowUpdate(
                id=self.tenant_workflow.id,
                workflow_state=TenantWorkflowStateType.active,
                wallet_bearer_token=self.tenant_workflow.wallet_bearer_token,
            )
            self._tenant_workflow = await self.workflow_repo.update(update_workflow)

            # first step is to initiate the connection to the Endorser
            endorser_alias = settings.ENDORSER_CONNECTION_ALIAS
            endorser_public_did = settings.ACAPY_ENDORSER_PUBLIC_DID
            connection = receive_invitation(
                endorser_alias, their_public_did=endorser_public_did
            )
            # add the endorser connection id to our tenant issuer setup
            update_issuer = TenantIssuerUpdate(
                id=tenant_issuer.id,
                workflow_id=self.tenant_workflow.id,
                endorser_connection_id=connection.connection_id,
                endorser_connection_state=connection.state,
            )
            tenant_issuer = await self.issuer_repo.update(update_issuer)

        # if workflow is "active" we need to check what state we are at,
        # ... and initiate the next step (if applicable)
        # called on receipt of webhook, so need to put the proper tenant "in context"
        elif self.tenant_workflow.workflow_state == TenantWorkflowStateType.active:
            logger.warn(
                f">>> run_step() called for active workflow with {webhook_message}"
            )
            webhook_topic = webhook_message["topic"]
            if webhook_topic == WebhookTopicType.connections:
                # check if we need to update the connection state in our issuer record
                connection_state = webhook_message["payload"]["state"]
                connection_id = webhook_message["payload"]["connection_id"]
                if not connection_state == tenant_issuer.endorser_connection_state:
                    update_issuer = TenantIssuerUpdate(
                        id=tenant_issuer.id,
                        workflow_id=tenant_issuer.workflow_id,
                        endorser_connection_id=tenant_issuer.endorser_connection_id,
                        endorser_connection_state=connection_state,
                    )
                    tenant_issuer = await self.issuer_repo.update(update_issuer)

                if (
                    connection_state == ConnectionStateType.active
                    or connection_state == ConnectionStateType.completed
                ):
                    # attach some meta-data to the connection
                    # TODO verify response from each call ...
                    data = {"transaction_my_job": "TRANSACTION_AUTHOR"}
                    endorse_api.transactions_conn_id_set_endorser_role_post(
                        connection_id, **data
                    )
                    endorser_alias = settings.ENDORSER_CONNECTION_ALIAS
                    endorser_public_did = settings.ACAPY_ENDORSER_PUBLIC_DID
                    data = {"endorser_name": endorser_alias}
                    endorse_api.transactions_conn_id_set_endorser_info_post(
                        connection_id, endorser_public_did, **data
                    )

                    # onto the next phase!  create our DID and make it public
                    data = {"body": DIDCreate()}
                    did_result = wallet_api.wallet_did_create_post(**data)
                    connection_state = tenant_issuer.endorser_connection_state
                    update_issuer = TenantIssuerUpdate(
                        id=tenant_issuer.id,
                        workflow_id=tenant_issuer.workflow_id,
                        endorser_connection_id=tenant_issuer.endorser_connection_id,
                        endorser_connection_state=connection_state,
                        public_did=did_result.result.did,
                        public_did_state=PublicDIDStateType.private,
                    )
                    tenant_issuer = await self.issuer_repo.update(update_issuer)

                    # post to the ledger (this will be an endorser operation)
                    # (just ignore the response for now)
                    try:
                        data = {"alias": tenant_issuer.tenant_id}
                        ledger_api.ledger_register_nym_post(
                            did_result.result.did,
                            did_result.result.verkey,
                            **data,
                        )
                        connection_state = tenant_issuer.endorser_connection_state
                        update_issuer = TenantIssuerUpdate(
                            id=tenant_issuer.id,
                            workflow_id=tenant_issuer.workflow_id,
                            endorser_connection_id=tenant_issuer.endorser_connection_id,
                            endorser_connection_state=connection_state,
                            public_did=tenant_issuer.public_did,
                            public_did_state=PublicDIDStateType.requested,
                        )
                        tenant_issuer = await self.issuer_repo.update(update_issuer)
                    except Exception:
                        # TODO this is a hack (for now) - aca-py 0.7.3 doesn't support
                        # the endorser protocol for this transacion, it will be in the
                        # next release (0.7.4 or whatever)
                        genesis_url = settings.ACAPY_GENESIS_URL
                        did_registration_url = genesis_url.replace(
                            "genesis", "register"
                        )
                        data = {
                            "did": did_result.result.did,
                            "verkey": did_result.result.verkey,
                            "alias": str(tenant_issuer.tenant_id),
                        }
                        requests.post(did_registration_url, json=data)

                        # now make it public
                        did_result = wallet_api.wallet_did_public_post(
                            did_result.result.did
                        )

                        connection_state = tenant_issuer.endorser_connection_state
                        update_issuer = TenantIssuerUpdate(
                            id=tenant_issuer.id,
                            workflow_id=tenant_issuer.workflow_id,
                            endorser_connection_id=tenant_issuer.endorser_connection_id,
                            endorser_connection_state=connection_state,
                            public_did=tenant_issuer.public_did,
                            public_did_state=PublicDIDStateType.public,
                        )
                        tenant_issuer = await self.issuer_repo.update(update_issuer)

                        # finish off our workflow
                        update_workflow = TenantWorkflowUpdate(
                            id=self.tenant_workflow.id,
                            workflow_state=TenantWorkflowStateType.completed,
                            wallet_bearer_token=None,
                        )
                        self._tenant_workflow = await self.workflow_repo.update(
                            update_workflow
                        )

            elif webhook_topic == WebhookTopicType.endorse_transaction:
                # TODO once we need to handle endorsements
                pass

            else:
                logger.warn(f">>> ignoring topic for now: {webhook_topic}")

        # if workflow is "completed" or "error" then we are done
        else:
            pass

        return self.tenant_workflow