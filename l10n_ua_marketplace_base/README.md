# Ukraine - Marketplace Base

Base module for Ukrainian marketplace integrations (feeds, order import, webhooks).

## Upgrading to 19.0.1.5.2

The webhook endpoint now requires a signature. Before upgrading, open every marketplace backend with **Enable Webhook** turned on and set **Webhook Secret** — the same value that is configured on the marketplace side. Backends with webhooks enabled and no secret will reject incoming webhook calls after the upgrade.
