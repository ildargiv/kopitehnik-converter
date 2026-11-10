# Security policy

## Supported versions

Only the [latest release](https://github.com/ildargiv/kopitehnik-converter/releases/latest) receives fixes.

## Reporting a vulnerability

Please do not open a public issue for a security problem.

Report it privately: the **Security** tab of this repository, then **Report a vulnerability**
(<https://github.com/ildargiv/kopitehnik-converter/security/advisories/new>).

Include the version, the operating system, what you did and what happened. A proof of concept helps, a fix is not required. You can expect a first answer within a week.

## What is in scope

- Files the program opens (images, PDF, Word, Excel, PowerPoint, scans) that make it run code, or write or delete files outside the chosen folders.
- The MCP server and the command-line modes (see [MCP.md](MCP.md)): calls that reach files the user did not point them to.
- The installer and the release build.

## Checking a download

Releases are built by GitHub Actions from this repository ([release workflow](.github/workflows/release.yml)) and carry `SHA256SUMS.txt` and a build provenance attestation. To check the installer:

```
certutil -hashfile KopiTehnik-Converter-Setup.exe SHA256
gh attestation verify KopiTehnik-Converter-Setup.exe --repo ildargiv/kopitehnik-converter
```

The installer is not code-signed, so Windows SmartScreen may warn on first start.
