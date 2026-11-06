# Run the server on the Mac

Use this to test before the Home Assistant app exists, or to debug.

1. Point the washer's cloud host to the Mac (DNS override). See the network
   runbook (not in this repository).
2. Import the login replies from a mitmproxy capture, once. They are device
   secrets; they go only to `data/login.json` (git ignores `data/`):

   ```bash
   .venv/bin/python -m scripts.import_login <path/to/messages.jsonl> data
   ```

   Without a capture: start the server and turn the cloud on once on the
   admin page. The server then records the replies itself.
3. Start the server. It needs port 443:

   ```bash
   home/run-local.sh
   ```

4. Switch the washer on. The log shows "Washer connected" and the state.
