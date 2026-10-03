const DATE_PATTERN = /^(\d{1,2})\/(\d{1,2})\/(\d{4})$/;
const ISO_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})(?:$|T)/;

function isValidDateParts(year, month, day) {
    const date = new Date(year, month - 1, day);
    return date.getFullYear() === year
        && date.getMonth() === month - 1
        && date.getDate() === day;
}

export function formatReadingDate(value) {
    if (!value) return '—';

    const isoMatch = String(value).match(ISO_DATE_PATTERN);
    if (isoMatch) {
        const [, year, month, day] = isoMatch;
        if (isValidDateParts(Number(year), Number(month), Number(day))) {
            return `${day}/${month}/${year}`;
        }
        return '—';
    }

    const date = value instanceof Date ? value : new Date(value);
    if (!Number.isFinite(date.getTime())) return '—';
    return [
        String(date.getDate()).padStart(2, '0'),
        String(date.getMonth() + 1).padStart(2, '0'),
        String(date.getFullYear()).padStart(4, '0'),
    ].join('/');
}

export function parseReadingDateInput(value, { required = false } = {}) {
    const text = String(value || '').trim();
    if (!text) {
        if (required) throw new Error('Podaj datę zwrotu w formacie dd/mm/yyyy.');
        return '';
    }

    const match = text.match(DATE_PATTERN);
    if (!match) throw new Error('Data musi mieć format dd/mm/yyyy.');

    const [, rawDay, rawMonth, year] = match;
    const day = rawDay.padStart(2, '0');
    const month = rawMonth.padStart(2, '0');
    if (!isValidDateParts(Number(year), Number(month), Number(day))) {
        throw new Error('Data zwrotu jest nieprawidłowa.');
    }
    return `${year}-${month}-${day}`;
}
