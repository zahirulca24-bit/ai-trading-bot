# AI Trading Bot — Safety Patch

This code uses Bybit **Demo** by default (`demo=True, testnet=False`). Never switch to a funded account without testing and review.

## Environment variables
Set `BYBIT_API_KEY`, `BYBIT_API_SECRET`, `GROQ_API_KEY`, `GEMINI_API_KEY`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID` using your deployment secret manager. Set a strong random `TRIGGER_TOKEN` to explicitly enable manual triggering.

`POST /trigger` requires `Authorization: Bearer <TRIGGER_TOKEN>`; if `TRIGGER_TOKEN` is absent, manual triggering is disabled. Do not expose `/status` publicly if account size is sensitive.

## Safety limits
- Trading only proceeds with verified exchange position status, equity, and available margin.
- Each proposed trade must fit its per-trade stop-risk, the 6% aggregate open-position stop-risk cap, 70% of available margin at 3x leverage, and at most 3 open positions.
- Position checks never purge local tracking after API errors. New orders use a cross-process file lock to prevent concurrent AI cycles on a shared filesystem.
- After exchange acknowledgement, order fills are verified before split TP placement. Any unverified fill or failed TP setup is escalated for **manual reconciliation**. Do not assume every order error means nothing was filled.

## Operational caveats
- File locking uses `fcntl`, for Linux/POSIX and a **single shared filesystem**, not a distributed lock. Run exactly one trading instance across the deployment. Deployments with multiple isolated replicas require a distributed lock and order idempotency keys before trading.
- Broker orders may be partially filled, cancel asynchronously, or remain open. Review all exchange positions, protective stops, and reduce-only exits following a restart or any error.
- A stop loss does not guarantee maximum realized loss in volatile markets. Fees, funding, slippage, liquidation and market gaps are not captured by stop-distance sizing.
- Do not treat AI confidence as an estimated win rate. Backtesting and demo-order integration tests are prerequisites for live use.
- Existing `state.json` daily balance tracking depends on a persistent filesystem and the runtime's local calendar date.

## Smoke tests
Run `python -m unittest discover -s tests -v` in an environment with `requirements.txt` installed. Mock-only tests do not submit exchange orders.
