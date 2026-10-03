import { networkInterfaces } from 'node:os';
import process from 'node:process';

const forceColor = Boolean(process.env.FORCE_COLOR && process.env.FORCE_COLOR !== '0');
const color = !process.env.NO_COLOR && (process.stdout.isTTY || forceColor);
const cyan = (text) => color ? `\x1b[36m${text}\x1b[0m` : text;
const green = (text) => color ? `\x1b[32m${text}\x1b[0m` : text;
const dim = (text) => color ? `\x1b[90m${text}\x1b[0m` : text;

const logo = String.raw`
   _____ _      ______          _   _ _____ _   _  _____
  / ____| |    |  ____|   /\   | \ | |_   _| \ | |/ ____|
 | |    | |    | |__     /  \  |  \| | | | |  \| | |  __
 | |    | |    |  __|   / /\ \ |  _  | | | |  _  | | |_ |
 | |____| |____| |____ / ____ \| |\  |_| |_| |\  | |__| |
  \_____|______|______/_/    \_\_| \_|_____|_| \_|\_____|
                 D A S H B O A R D
`;

const addresses = [];
for (const entries of Object.values(networkInterfaces())) {
  for (const entry of entries || []) {
    if (entry.family === 'IPv4' && !entry.internal) addresses.push(entry.address);
  }
}

console.log(cyan(logo));
console.log(green('DEV CONTROL  //  one terminal, four local services'));
console.log(dim('The frontend uses Vite. /api calls are proxied to the local SQLite backend.'));
console.log(dim('Network Monitor scans your LAN; Mi Scale listens for BLE advertisements.'));
console.log('');
console.log('SERVICES');
console.log('  [API]    Dashboard data and integrations     http://127.0.0.1:8000');
console.log('  [NET]    Local network monitor               http://127.0.0.1:8765');
console.log('  [SCALE]  Xiaomi Mi Scale 2 BLE listener      continuous');
console.log('  [VITE]   Dashboard frontend                  http://localhost:5173/cleaning-dashboard/');
for (const address of addresses) {
  console.log(`  [LAN]    Kitchen screen                      http://${address}:5173/cleaning-dashboard/kitchen.html`);
}
console.log('');
console.log('COMMANDS');
console.log('  rs              restart only [API] (run in a second terminal)');
console.log('  stop-dev        stop only this project\'s dev services');
console.log('  h + Enter       show Vite help');
console.log('  npm run help    show all project commands');
console.log('  close window    stop the stack');
console.log('');
console.log('LOGS');
console.log('  Console: compact (writes, redirects, warnings and errors).');
console.log('  File:    full HTTP history remains in server.log.');
console.log('  Set DASHBOARD_HTTP_LOG=all before startup to restore every request.');
console.log('');
