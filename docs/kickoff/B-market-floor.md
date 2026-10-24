# Lane B: Market and screens (SpacetimeDB, Next.js, three.js, Cartesia)
Paste 00-shared.md first, then this.

You own market/ and web/. Goal: one live shared market everyone sees, and the 3D floor as a view on top of it.

Tasks in order:
1. SpacetimeDB module: tables for needs, bids, claims, verdicts, orders, personas; reducers post_need, place_bid, counter, close_auction, attach_verdict, attach_claim_check. Auction rule: reverse auction with a deadline; best bid by price minus perks value, ties to verified claims. Unit-test the rule. (Spacetime's track asks for live shared state; auctions and marketplaces are named in their text.) If the module blocks you past Sat 00:00, fall back to Convex and tell the board.
2. Shopper web view: post a need, watch bids land live, see advocate warnings, approve (mirrors the ASI:One flow for the big screen).
3. Store dashboard: orders won and lost with the reason, wind-tunnel results, ledger summary.
4. 3D Bazaar floor (three.js or react-three-fiber): a market square with stalls; each store agent is a rigged low-poly character (free CC0 characters with idle, haggle, cheer, sulk animations), speech bubbles show live bids, the advocate stands by the shopper, the Shield guard drags blocked agents out. Every motion is driven by market state only. About 8 characters on screen; 2D sprites are the fallback.
5. Voices: each persona speaks its bid with its own Cartesia voice (cache audio per bid; mute toggle).
6. Optional hardware terminal: camera scan of a barcode plus a touch screen showing bids (ESP32-S3 display or Raspberry Pi from the hardware desk); fallback is a webcam scan in the browser.
Done when: two laptops see the same auction and the same floor in real time, and the floor never shows anything the market did not record.
