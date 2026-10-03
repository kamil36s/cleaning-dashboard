import { describe, expect, it } from 'vitest';
import {
  formatLanguageRoute,
  parseLanguageRoute,
  routeHeading,
  routeSection,
} from '../js/language/router.js';

describe('Language hash router', () => {
  it('parses an empty hash and overview as Overview', () => {
    expect(parseLanguageRoute('')).toEqual({ name: 'overview', valid: true });
    expect(parseLanguageRoute('#overview')).toEqual({ name: 'overview', valid: true });
  });

  it('parses all simple application routes', () => {
    expect(parseLanguageRoute('#inbox')).toEqual({ name: 'inbox', valid: true });
    expect(parseLanguageRoute('#reader')).toEqual({ name: 'reader', valid: true });
    expect(parseLanguageRoute('#listening')).toEqual({ name: 'listening', valid: true });
    expect(parseLanguageRoute('#vocabulary')).toEqual({ name: 'vocabulary', valid: true });
    expect(parseLanguageRoute('#phrasebook')).toEqual({ name: 'phrasebook', valid: true });
    expect(parseLanguageRoute('#topics')).toEqual({ name: 'topics', valid: true });
    expect(parseLanguageRoute('#statistics')).toEqual({ name: 'statistics', valid: true });
    expect(parseLanguageRoute('#goals')).toEqual({ name: 'goals', valid: true });
    expect(parseLanguageRoute('#settings')).toEqual({ name: 'settings', valid: true });
  });

  it('parses and formats Content Inbox and authentic Listening routes', () => {
    const inbox = { name: 'inboxContent', contentId: 'content ü' };
    const listening = { name: 'listeningContent', contentId: 'content ü' };
    expect(parseLanguageRoute(formatLanguageRoute(inbox))).toEqual({ ...inbox, valid: true });
    expect(parseLanguageRoute(formatLanguageRoute(listening))).toEqual({ ...listening, valid: true });
    expect(routeSection(inbox)).toBe('inbox');
    expect(routeHeading(listening)).toBe('Authentic Listening');
  });

  it('parses direct lemma routes for reload-safe detail loading', () => {
    expect(parseLanguageRoute('#vocabulary/lemma/abc123')).toEqual({
      name: 'lemma', lemmaId: 'abc123', valid: true,
    });
  });

  it('parses and formats direct Reader text routes', () => {
    const route = { name: 'readerText', textId: 'text ü' };
    expect(formatLanguageRoute(route)).toBe('#reader/text/text%20%C3%BC');
    expect(parseLanguageRoute(formatLanguageRoute(route))).toEqual({ ...route, valid: true });
    expect(routeSection(route)).toBe('reader');
    expect(routeHeading(route)).toBe('Reader');
  });

  it('parses and formats direct Listening text routes', () => {
    const route = { name: 'listeningText', textId: 'text ü' };
    expect(formatLanguageRoute(route)).toBe('#listening/text/text%20%C3%BC');
    expect(parseLanguageRoute(formatLanguageRoute(route))).toEqual({ ...route, valid: true });
    expect(routeSection(route)).toBe('listening');
    expect(routeHeading(route)).toBe('Listening');
  });

  it('decodes and formats lemma IDs safely', () => {
    const route = { name: 'lemma', lemmaId: 'lemma ü' };
    expect(formatLanguageRoute(route)).toBe('#vocabulary/lemma/lemma%20%C3%BC');
    expect(parseLanguageRoute(formatLanguageRoute(route))).toEqual({ ...route, valid: true });
  });

  it('rejects missing IDs, extra segments, and malformed encoding', () => {
    expect(parseLanguageRoute('#vocabulary/lemma/').valid).toBe(false);
    expect(parseLanguageRoute('#vocabulary/lemma/a/more').valid).toBe(false);
    expect(parseLanguageRoute('#vocabulary/lemma/%E0%A4%A').valid).toBe(false);
  });

  it('returns an invalid Overview fallback with the original route', () => {
    expect(parseLanguageRoute('#future')).toEqual({
      name: 'overview', valid: false, invalidHash: 'future',
    });
  });

  it('formats supported simple routes and safely falls back', () => {
    expect(formatLanguageRoute('overview')).toBe('#overview');
    expect(formatLanguageRoute({ name: 'vocabulary' })).toBe('#vocabulary');
    expect(formatLanguageRoute({ name: 'phrasebook' })).toBe('#phrasebook');
    expect(formatLanguageRoute({ name: 'settings' })).toBe('#settings');
    expect(formatLanguageRoute({ name: 'reader' })).toBe('#reader');
    expect(formatLanguageRoute({ name: 'listening' })).toBe('#listening');
    expect(formatLanguageRoute({ name: 'topics' })).toBe('#topics');
    expect(formatLanguageRoute({ name: 'statistics' })).toBe('#statistics');
    expect(formatLanguageRoute({ name: 'goals' })).toBe('#goals');
  });

  it('maps lemma detail to the persistent Vocabulary shell section', () => {
    expect(routeSection({ name: 'lemma' })).toBe('vocabulary');
    expect(routeHeading({ name: 'lemma' })).toBe('Vocabulary');
  });
});
