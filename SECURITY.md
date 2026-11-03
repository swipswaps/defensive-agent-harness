# Security Policy

## Supported versions

Only the `main` branch is supported. The harness is a local lab tool and does
not provide a hosted service.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting for this repository:

- Repository Security tab -> Report a vulnerability

Do not open a public issue for an unpatched vulnerability. Include:

- affected commit or file
- reproduction steps
- whether the issue crosses the documented isolation boundary
- any evidence that the audit chain or snapshot recovery was bypassed

## Scope and trust boundary

In scope:

- container escape from the documented Compose configuration
- path traversal or link abuse in snapshot recovery
- audit-chain or anchor bypass
- integrity-manifest bypass
- unsafe default behavior that produces a vacuous success

Out of scope:

- kernel or hardware side channels (Docker shares the host kernel)
- a hostile host, compromised Docker daemon, or compromised registry
- misuse of `--allow-empty-target` for a real probe
- denial of service by the operator against their own host

See `README.txt` for the full list of guarantees and non-guarantees.
