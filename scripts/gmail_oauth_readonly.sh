#!/usr/bin/env bash
# Re-authenticate Gmail MCP with gmail.readonly only.
# The published @gongrzhe/server-gmail-autoauth-mcp auth command always
# requests gmail.modify + gmail.settings.basic. This script writes a
# credentials.json that Google will only allow to read mail (OTP use-case).
#
# Usage (WSL):
#   bash scripts/gmail_oauth_readonly.sh
#
# Then revoke the old grant at:
#   https://myaccount.google.com/permissions
set -euo pipefail

GMAIL_DIR="${HOME}/.gmail-mcp"
KEYS="${GMAIL_DIR}/gcp-oauth.keys.json"
CREDS="${GMAIL_DIR}/credentials.json"
CALLBACK="${GMAIL_OAUTH_CALLBACK:-http://localhost:3000/oauth2callback}"

if [[ ! -f "$KEYS" ]]; then
  echo "Missing $KEYS"
  echo "Download a Desktop OAuth client JSON from Google Cloud Console and save it there."
  exit 1
fi

# Prefer the npx-cached package (has google-auth-library); fall back to npm install.
PKG_ROOT="$(find "${HOME}/.npm/_npx" -path '*@gongrzhe/server-gmail-autoauth-mcp/package.json' 2>/dev/null | head -1 || true)"
if [[ -z "$PKG_ROOT" ]]; then
  echo "Caching @gongrzhe/server-gmail-autoauth-mcp via npx..."
  npx -y --package=@gongrzhe/server-gmail-autoauth-mcp true >/dev/null 2>&1 || \
    npx -y @gongrzhe/server-gmail-autoauth-mcp --help >/dev/null 2>&1 || true
  PKG_ROOT="$(find "${HOME}/.npm/_npx" -path '*@gongrzhe/server-gmail-autoauth-mcp/package.json' 2>/dev/null | head -1 || true)"
fi
if [[ -z "$PKG_ROOT" ]]; then
  echo "Could not locate @gongrzhe/server-gmail-autoauth-mcp under ~/.npm/_npx"
  exit 1
fi
PKG_DIR="$(dirname "$PKG_ROOT")"

# Resolve google-auth-library from the MCP install tree
GAL=""
for cand in \
  "${PKG_DIR}/node_modules/google-auth-library" \
  "${PKG_DIR}/../google-auth-library" \
  "${PKG_DIR}/../../google-auth-library"
do
  if [[ -d "$cand" ]]; then
    GAL="$cand"
    break
  fi
done
if [[ -z "$GAL" ]]; then
  GAL="$(find "${HOME}/.npm/_npx" -type d -path '*/node_modules/google-auth-library' 2>/dev/null | head -1 || true)"
fi
if [[ -z "$GAL" ]]; then
  echo "Could not find google-auth-library next to the Gmail MCP package"
  exit 1
fi

if [[ -f "$CREDS" ]]; then
  echo "Backing up existing credentials to ${CREDS}.bak"
  cp -f "$CREDS" "${CREDS}.bak"
  rm -f "$CREDS"
fi

export KEYS CREDS CALLBACK GAL
node <<'NODE'
const fs = require("fs");
const http = require("http");
const path = require("path");
const { OAuth2Client } = require(process.env.GAL);

const keysFile = JSON.parse(fs.readFileSync(process.env.KEYS, "utf8"));
const installed = keysFile.installed || keysFile.web;
if (!installed) {
  console.error("gcp-oauth.keys.json must contain installed or web credentials");
  process.exit(1);
}

const callback = process.env.CALLBACK;
const client = new OAuth2Client(installed.client_id, installed.client_secret, callback);
const SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"];

const server = http.createServer();
server.listen(3000, () => {
  const authUrl = client.generateAuthUrl({
    access_type: "offline",
    prompt: "consent",
    scope: SCOPES,
  });
  console.log("Open this URL and approve READ-ONLY Gmail access:");
  console.log(authUrl);
  console.log("");
  console.log("Waiting for callback on", callback);
});

server.on("request", async (req, res) => {
  if (!req.url || !req.url.startsWith("/oauth2callback")) return;
  const url = new URL(req.url, "http://localhost:3000");
  const code = url.searchParams.get("code");
  if (!code) {
    res.writeHead(400);
    res.end("No code provided");
    return;
  }
  try {
    const { tokens } = await client.getToken(code);
    fs.writeFileSync(process.env.CREDS, JSON.stringify(tokens, null, 2));
    res.writeHead(200, { "Content-Type": "text/plain" });
    res.end("Read-only Gmail auth successful. You can close this window.");
    console.log("Wrote", process.env.CREDS);
    console.log("Authorized scopes:", tokens.scope || SCOPES.join(" "));
    console.log("Revoke any older ApplyPilot/Gmail MCP grant at https://myaccount.google.com/permissions");
    server.close();
    process.exit(0);
  } catch (err) {
    res.writeHead(500);
    res.end("Authentication failed");
    console.error(err);
    process.exit(1);
  }
});
NODE
