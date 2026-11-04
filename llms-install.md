# Install KopiTehnik Converter MCP server (agent-facing)

KopiTehnik Converter is a **Windows** batch converter and print preparer for photo labs;
the MCP server is built into it. Windows 10/11 only.

## Option A - installed app

1. Download `KopiTehnik-Converter-Setup.exe` from
   <https://github.com/ildargiv/kopitehnik-converter/releases/latest> (per-user install, no admin needed).
2. Silent install: `KopiTehnik-Converter-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-`
3. Add to the MCP client config (adjust the path to your install folder):

```json
{
  "mcpServers": {
    "kopitehnik-converter": {
      "command": "C:\Users\<user>\AppData\Local\Programs\KopiTehnik Converter\Converter.exe",
      "args": ["--mcp"]
    }
  }
}
```

## Option B - PyPI launcher (any MCP client, needs uv)

```bash
uvx kopitehnik-converter-mcp
```

The launcher finds the installed `Converter.exe` and forwards stdio to it; nothing is
reimplemented in Python.

```json
{ "mcpServers": { "kopitehnik-converter": { "command": "uvx", "args": ["kopitehnik-converter-mcp"] } } }
```

Claude Desktop config: `%APPDATA%\Claude\claude_desktop_config.json` (restart Claude after editing).

## Sibling product

For actual printing (ICC colour, borderless, smart crop, sheet layout) see
[KopiTehnik Print](https://github.com/ildargiv/KopiTehnik-Print) - same agent interface, `uvx kopitehnik-print-mcp`.

Registry names: official MCP Registry `io.github.ildargiv/kopitehnik-converter`; PyPI `kopitehnik-converter-mcp`.
