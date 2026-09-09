---
title: Authentication and API Keys
doc_type: product
product: platform
effective_date: 2026-02-14
version: "4.1"
---

# Authentication and API Keys

## Key types

There are two kinds of credential. A **secret key** (`sk_live_...`) carries full
account privileges and must never reach a browser. A **publishable key**
(`pk_live_...`) is safe to embed in client code and can only create sessions.

## Rotating a key

Rotation is zero-downtime: both the old and new key are valid during the overlap
window.

1. Create the replacement key in the dashboard under Settings → API Keys.
2. Deploy the new key to every service that authenticates.
3. Confirm traffic on the old key has dropped to zero in the usage graph.
4. Revoke the old key.

The default overlap window is 7 days. After revocation the old key returns `E1002`
immediately; there is no grace period.

## Single sign-on

SAML and OIDC are available on Enterprise plans only. Configuration requires
uploading your identity provider's metadata XML and takes roughly 30 minutes.
SCIM user provisioning is supported alongside SAML but not alongside OIDC.
