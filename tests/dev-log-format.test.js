import { describe, expect, it } from 'vitest';

import {
  extractLogTime,
  formatLogColumns,
  startsTrace,
  stripAnsi,
} from '../scripts/dev-log-format.js';

describe('dev log formatting', () => {
  it('moves an ANSI-wrapped backend timestamp into the clock column', () => {
    const parsed = extractLogTime('\x1b[90m08:58:23\x1b[0m \x1b[35m[api]\x1b[0m Server starting...');
    expect(parsed.time).toBe('08:58:23');
    expect(stripAnsi(parsed.message)).toBe('[api] Server starting...');
  });

  it('normalizes a Werkzeug access log into the same time column', () => {
    const parsed = extractLogTime('127.0.0.1 - - [01/Aug/2026 08:58:24] "GET /api/network/summary HTTP/1.1" 200 -');
    expect(parsed).toEqual({
      time: '08:58:24',
      message: '127.0.0.1  "GET /api/network/summary HTTP/1.1" 200 -',
    });
  });

  it('keeps service and clock columns aligned for trace continuations', () => {
    const header = formatLogColumns({
      label: 'API',
      colorCode: 35,
      time: '08:58:23',
      message: 'Server starting...',
      useColor: false,
    });
    const continuation = formatLogColumns({
      label: 'VITE',
      colorCode: 32,
      time: '',
      message: 'Error: connect ECONNREFUSED',
      useColor: false,
    });
    expect(header).toBe('08:58:23 [API]   | Server starting...');
    expect(continuation).toBe('         [VITE]  | Error: connect ECONNREFUSED');
  });

  it('recognizes proxy headers and error lines as trace starts', () => {
    expect(startsTrace('[vite] http proxy error: /api/weight/latest')).toBe(true);
    expect(startsTrace('Error: connect ECONNREFUSED')).toBe(true);
    expect(startsTrace('VITE ready')).toBe(false);
  });

  it('uses an ASCII arrow that renders correctly in Windows cmd', () => {
    const line = formatLogColumns({
      label: 'VITE',
      colorCode: 32,
      time: '09:04:47',
      message: '\u279c Local: http://localhost:5173',
      useColor: false,
    });
    expect(line).toContain('-> Local:');
    expect(line).not.toContain('\u279c');
  });
});
