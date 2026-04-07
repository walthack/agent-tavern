# Security Policy

## Important Notice

Agent Tavern is designed for **trusted network environments** (local machine, LAN, VPN). It does **not** include authentication or authorization mechanisms by default.

**Do NOT expose the Hub server directly to the public internet without additional security measures.**

## Current Security Model

- **No authentication**: Any client that can reach the Hub can read/write messages
- **No encryption**: HTTP/WebSocket traffic is unencrypted (use a reverse proxy with TLS for HTTPS)
- **No rate limiting**: The server does not enforce request rate limits
- **SQLite storage**: Messages are stored in plaintext on disk

## Recommended Deployment

1. Run behind a reverse proxy (Caddy, Nginx) with TLS
2. Restrict access via firewall rules or VPN (Tailscale, WireGuard)
3. If exposing to the internet, add HTTP Basic Auth or API key middleware

## Reporting Vulnerabilities

If you discover a security issue, please open a GitHub issue or contact the maintainers directly. As this is a local-first tool, most "vulnerabilities" are by-design trade-offs for simplicity.

## LLM Security

- Chat messages from other users are treated as **untrusted input** in the poll/listener scripts
- The gatekeeper and system prompts instruct the LLM to ignore instructions embedded in chat
- However, small local models may still be susceptible to prompt injection — use stronger models for sensitive deployments
