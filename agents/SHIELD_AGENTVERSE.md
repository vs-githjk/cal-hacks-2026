# Tech Bazaar Shield Client

![tag:innovationlab](https://img.shields.io/badge/innovationlab-3D8BD3)
![tag:hackathon](https://img.shields.io/badge/hackathon-5F43F1)

A chat front door to Tech Bazaar's existing Bazaar Shield HTTP screening service. Send listing or agent-message text to @techbazaarshield in ASI:One to request screening. The client returns the service's screening result; it does not approve purchases, move money or operate a separate Shield server.

Requires a configured and reachable `SHIELD_URL`. If screening is unavailable or unconfigured, the client blocks the request and reports the failure instead of treating the text as safe.

Screening verdicts are evidence about configured rules, not a guarantee that a listing is trustworthy. Tech Bazaar's seller catalogs and prices are simulated (SIM). Start a shopping goal with @techbazaarbuyer.
