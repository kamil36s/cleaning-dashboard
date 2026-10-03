# Norwegian Cloze sentence audio

The Cloze view generates full-sentence Norwegian Bokmål audio on demand with Google Cloud Text-to-Speech. The server sends the frozen, unclozed `sentenceText` using `nb-NO` and one Chirp 3 HD voice. The browser never receives Google credentials.

## One-time setup

1. In a Google Cloud project with billing enabled, enable the **Cloud Text-to-Speech API**:

   ```powershell
   gcloud config set project your-project-id
   gcloud services enable texttospeech.googleapis.com
   ```
2. Install the server dependencies:

   ```powershell
   python -m pip install -r requirements-language.txt
   ```

3. Authenticate on the machine that runs the dashboard. For local development, Google's recommended ADC flow is:

   ```powershell
   gcloud init
   gcloud auth application-default login
   gcloud auth application-default set-quota-project your-project-id
   ```

   Alternatively, use a service-account credential file and set `GOOGLE_APPLICATION_CREDENTIALS` to its absolute path. Never commit that JSON file.

4. Add the project ID to `.env.development` (or `.env.production`):

   ```dotenv
   GOOGLE_CLOUD_PROJECT=your-project-id
   # Optional when ADC was configured with gcloud:
   GOOGLE_APPLICATION_CREDENTIALS=C:\absolute\private\path\service-account.json
   # Optional; this is the built-in default:
   NORWEGIAN_TTS_VOICE=nb-NO-Chirp3-HD-Kore
   ```

5. Restart the dashboard server, open Language → Cloze, start or resume a session, and click **Play sentence**. The first click may show “Generating audio…”. Later clicks reuse the local MP3.

Google documents [Cloud TTS authentication and ADC](https://docs.cloud.google.com/text-to-speech/docs/authentication), the available [Chirp 3 HD voices and `nb-NO` support](https://docs.cloud.google.com/text-to-speech/docs/chirp3-hd), and the [`text:synthesize` REST method](https://docs.cloud.google.com/text-to-speech/docs/reference/rest/v1/text/synthesize).

## Cache and API

- Files: `data/audio/language-learning/nb-NO/cloze/<sentence-id>_<cache-key>.mp3`
- Metadata: main SQLite schema v8, table `cloze_sentence_audio`
- Generate/cache lookup: `POST /api/language/cloze/sessions/:sessionId/items/:itemIndex/audio`
- Local playback: `GET /api/language/cloze/audio/:cacheKey.mp3`

The SHA-256 cache key includes the complete sentence text, language, provider, voice, MP3 encoding, and a synthesis-config version. Changing any of those values creates a new file; matching requests reuse the existing file and do not call Google. If metadata exists but the file is missing, the next request regenerates it. Audio is not pre-generated.
