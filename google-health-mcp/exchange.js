const fs = require('fs');
const { GoogleHealthClient } = require('/usr/local/lib/node_modules/google-health-mcp-unofficial/dist/services/google-health-client.js');
const { getConfig } = require('/usr/local/lib/node_modules/google-health-mcp-unofficial/dist/services/config.js');

async function main() {
  const input = process.argv[2];
  if (!input) {
    console.error("Usage: node exchange.js <redirect_url_or_code>");
    process.exit(1);
  }
  const flow = JSON.parse(fs.readFileSync('/app/data/current_auth_flow.json', 'utf8'));
  const config = getConfig();
  const client = new GoogleHealthClient(config);
  try {
    const result = await client.exchangeCode(input, flow.verifier);
    console.log("SUCCESS:", JSON.stringify(result, null, 2));
  } catch (err) {
    console.error("EXCHANGE_ERROR:", err.message);
    process.exit(1);
  }
}

main();
