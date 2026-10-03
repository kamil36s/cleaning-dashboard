const screensaverLink = document.querySelector('.dashboard-screensaver-link');

if (screensaverLink) {
  screensaverLink.addEventListener('click', async (event) => {
    event.preventDefault();

    const targetUrl = new URL(screensaverLink.getAttribute('href'), window.location.href).toString();

    try {
      if (!document.fullscreenElement && document.documentElement.requestFullscreen) {
        await document.documentElement.requestFullscreen();
      }
    } catch (error) {
      console.warn('Could not enter fullscreen before opening Spotify screensaver:', error);
    } finally {
      window.location.assign(targetUrl);
    }
  });
}
