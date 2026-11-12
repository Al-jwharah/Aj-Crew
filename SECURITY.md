# Security Policy

## Reporting a Vulnerability

If you discover a potential security issue in this project, please **do not** create a public
GitHub issue. Instead, report it privately:

- **Private advisory:** open a report at
  <https://github.com/Al-jwharah/Aj-Crew/security/advisories/new> (GitHub's private
  vulnerability reporting for this repository).
- **If that page is not available to you:** contact the maintainer privately through the
  contact details on their GitHub profile, <https://github.com/Al-jwharah>, and say only that
  you have a security report for Aj Crew. Send the details once a private channel is agreed.

Please include:
- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

Reports are handled on a best-effort basis by the maintainer of this fork.

### Issues that also affect upstream

Aj Crew is an independent fork of [Kiro Crew](https://github.com/kirodotdev/KiroCrew). If the
issue is in code this fork inherited unchanged, it very likely affects upstream too, and
upstream can only fix it there if it hears about it. Upstream has its own contact,
`kiro-crew-security-support@amazon.com`. That address belongs to the upstream project: it does
not handle reports about Aj Crew, so report here first and use it only for the upstream
product.

## Supported Versions

Aj Crew has not published a release yet, so the supported version is the current `main`
branch: fixes land there, and a source install picks them up with `git pull` followed by
`ajcrew update`. Once releases exist, only the latest one is supported with security patches.

## Scope

This policy covers the Aj Crew source code and its bundled dependencies. It does not cover
third-party services (LLM providers, etc.) that Aj Crew connects to.
