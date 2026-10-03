const ANSI_PATTERN = '\\x1b\\[[0-9;]*m';
const ANSI_GLOBAL = new RegExp(ANSI_PATTERN, 'g');
const LEADING_CLOCK = new RegExp(`^(?:${ANSI_PATTERN})*(\\d{2}:\\d{2}:\\d{2})(?:${ANSI_PATTERN})*\\s+(.*)$`, 's');
const WERKZEUG_REQUEST = /^(\S+)\s+-\s+-\s+\[[^\]]+\s+(\d{2}:\d{2}:\d{2})\]\s+(.*)$/s;

export const SERVICE_COLUMN_WIDTH = 7;

export function stripAnsi(value) {
  return String(value || '').replace(ANSI_GLOBAL, '');
}

export function extractLogTime(line) {
  const value = String(line || '');
  const leading = value.match(LEADING_CLOCK);
  if (leading) return { time: leading[1], message: leading[2] };

  const plain = stripAnsi(value);
  const werkzeug = plain.match(WERKZEUG_REQUEST);
  if (werkzeug) {
    return {
      time: werkzeug[2],
      message: `${werkzeug[1]}  ${werkzeug[3]}`,
    };
  }
  return { time: '', message: value };
}

export function startsTrace(message) {
  const plain = stripAnsi(message).trim();
  return /(?:\[vite\]\s+http proxy error|^error\b|^traceback\b|^caused by\b)/i.test(plain);
}

export function formatLogColumns({ label, colorCode, time, message, useColor }) {
  const rawLabel = `[${label}]`.padEnd(SERVICE_COLUMN_WIDTH, ' ');
  const visibleLabel = useColor ? `\x1b[${colorCode}m${rawLabel}\x1b[0m` : rawLabel;
  const clock = String(time || '').padEnd(8, ' ');
  const cleanMessage = String(message || '').replace(/\u279c/g, '->');
  return `${clock} ${visibleLabel} | ${cleanMessage}`;
}
