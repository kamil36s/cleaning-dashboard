const SPOTIFY_MARK = `
  <svg class="spotify-mark" aria-hidden="true" viewBox="0 0 24 24" focusable="false">
    <circle cx="12" cy="12" r="12" fill="#1ed760"></circle>
    <path d="M6.4 9.1c3.9-1.2 8.1-.8 11.3.9" fill="none" stroke="#07140c" stroke-width="1.75" stroke-linecap="round"></path>
    <path d="M7.2 12.2c3.2-.9 6.8-.6 9.5.8" fill="none" stroke="#07140c" stroke-width="1.55" stroke-linecap="round"></path>
    <path d="M8 15.1c2.6-.7 5.3-.5 7.6.6" fill="none" stroke="#07140c" stroke-width="1.4" stroke-linecap="round"></path>
  </svg>
`;

const YOUTUBE_MARK = `
  <svg class="youtube-mark" aria-hidden="true" viewBox="0 0 24 24" focusable="false">
    <path fill="#ff0033" d="M23.3 7.2a3 3 0 0 0-2.1-2.1C19.3 4.6 12 4.6 12 4.6s-7.3 0-9.2.5A3 3 0 0 0 .7 7.2 31 31 0 0 0 .2 12a31 31 0 0 0 .5 4.8 3 3 0 0 0 2.1 2.1c1.9.5 9.2.5 9.2.5s7.3 0 9.2-.5a3 3 0 0 0 2.1-2.1 31 31 0 0 0 .5-4.8 31 31 0 0 0-.5-4.8Z"></path>
    <path fill="#fff" d="m9.6 15.4 6.2-3.4-6.2-3.4v6.8Z"></path>
  </svg>
`;

const RATEYOURMUSIC_MARK = `
  <svg class="rateyourmusic-mark" aria-hidden="true" viewBox="0 0 143 143" focusable="false">
    <path fill="#e6e4e5" d="M85.8 43c10.9 4.4 30.1 3.8 42 2.7C118 24.2 96.2 9.2 71.2 9.2c-12.1 0-23.2 3.3-32.8 9.4C59.3 8.8 69.3 36.1 85.8 43Z"></path>
    <path fill="#e6e4e5" d="M142.2 71.4c0 39.3-31.7 71-71 71s-71-31.7-71-71 31.7-71 71-71 71 32 71 71Z"></path>
    <path fill="#5db4e4" d="M107.7 67.9c9.6.6 18.4-1.9 25.1-4.8-.8-6.3-2.5-12.1-5-17.5-11.9 1-31.1 1.7-42-2.7-16.5-6.9-27.4-34.7-47.4-24.4C20.6 29.4 8.9 48.9 8.9 71.4c0 5.8.8 11.5 2.3 16.7 9.8-8.8 30.5-25.3 49.1-30.3 25.1-6.7 26.7 8.8 47.4 10.1Z"></path>
    <path fill="#2d6fbd" d="M132.8 63.3c-6.7 2.9-15.5 5.2-25.1 4.8C87 66.8 85.4 51.2 60.1 58 41.7 63.1 21.1 79.8 11 88.3c2.1 7.1 5.2 13.8 9.6 19.9 6.7-5.6 14.8-10.9 23.8-12.8 25.7-5.4 25.7 13 47.4 10.5 11.9-1.5 28.2-12.9 40.5-22.9.7-3.6 1.1-7.4 1.1-11.1 0-3.2-.2-5.9-.6-8.6Z"></path>
    <path fill="#1d4488" d="M44.4 95.2c-9 1.9-17.1 7.1-23.8 12.7 11.3 15.7 29.7 25.9 50.6 25.9 30.7 0 56-22.1 61.2-51.1-12.4 10-28.6 21.5-40.5 23-21.8 2.5-21.8-16.1-47.5-10.5Z"></path>
    <path fill="#1c3e75" d="M97.3 83.1c2.5 6.3.2 13.2-5.6 15.7-5.7 2.3-12.4-.8-15.1-6.9-2.5-6.3-.2-13.2 5.6-15.7 5.9-2.5 12.6.6 15.1 6.9Z"></path>
  </svg>
`;

function spotifySearchUrl(...terms) {
  const query = terms.map((term) => String(term || '').trim()).filter(Boolean).join(' ');
  return `https://open.spotify.com/search/${encodeURIComponent(query)}`;
}

function youtubeSearchUrl(...terms) {
  const query = terms.map((term) => String(term || '').trim()).filter(Boolean).join(' ');
  return `https://www.youtube.com/results?search_query=${encodeURIComponent(query)}`;
}

function rateYourMusicSearchUrl(...terms) {
  const query = terms.map((term) => String(term || '').trim()).filter(Boolean).join(' ');
  return `https://rateyourmusic.com/search?searchterm=${encodeURIComponent(query)}&searchtype=`;
}

function spotifyMarkMarkup() {
  return SPOTIFY_MARK;
}

function youtubeMarkMarkup() {
  return YOUTUBE_MARK;
}

function rateYourMusicMarkMarkup() {
  return RATEYOURMUSIC_MARK;
}

function createSpotifySearchLink(...terms) {
  const query = terms.map((term) => String(term || '').trim()).filter(Boolean).join(' - ');
  const link = document.createElement('a');
  link.className = 'media-icon-action spotify-icon-action';
  link.href = spotifySearchUrl(...terms);
  link.target = '_blank';
  link.rel = 'noopener';
  link.title = 'Search on Spotify';
  link.setAttribute('aria-label', `Search on Spotify: ${query}`);
  link.innerHTML = spotifyMarkMarkup();
  return link;
}

function createYoutubeSearchLink(...terms) {
  const query = terms.map((term) => String(term || '').trim()).filter(Boolean).join(' - ');
  const link = document.createElement('a');
  link.className = 'media-icon-action youtube-icon-action';
  link.href = youtubeSearchUrl(...terms);
  link.target = '_blank';
  link.rel = 'noopener';
  link.title = 'Search on YouTube';
  link.setAttribute('aria-label', `Search on YouTube: ${query}`);
  link.innerHTML = youtubeMarkMarkup();
  return link;
}

function createRateYourMusicSearchLink(...terms) {
  const query = terms.map((term) => String(term || '').trim()).filter(Boolean).join(' - ');
  const link = document.createElement('a');
  link.className = 'media-icon-action rateyourmusic-icon-action';
  link.href = rateYourMusicSearchUrl(...terms);
  link.target = '_blank';
  link.rel = 'noopener';
  link.title = 'Search on Rate Your Music';
  link.setAttribute('aria-label', `Search on Rate Your Music: ${query}`);
  link.innerHTML = rateYourMusicMarkMarkup();
  return link;
}

export {
  createRateYourMusicSearchLink,
  createSpotifySearchLink,
  createYoutubeSearchLink,
  rateYourMusicMarkMarkup,
  rateYourMusicSearchUrl,
  spotifyMarkMarkup,
  spotifySearchUrl,
  youtubeMarkMarkup,
  youtubeSearchUrl,
};
