# SofaStream work rules

- Do new work on `development` or a feature branch based on it. Do not push new
  features directly to `main`; use a pull request for stable releases.
- Never commit user settings, follows, credentials, pairing data or logs.
- `sofastream` and `sofastream@dev` belong to the same Homebrew tap. Keep their
  config/cache directories, Streamlink ports and launchctl labels separate.
- CI uses fixtures. Do not discover, wake, pair, play, stop or otherwise contact
  a real Apple TV without explicit authorization for that hardware check.
- A user saying the Apple TV is in use means leave playback completely alone.
- Local paths belong in environment variables or computed defaults, not source.
- Keep previously working controls, import safeguards and cancellation behavior.
