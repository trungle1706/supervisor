# Console design reference (2026-10-15)

`console-prototype.html` is the approved look and information architecture for the reviewer console (WP12 rebuild). Open it in a browser; the left rail switches screens. The PNGs are reference renders at 1360x900.

Design rules the real console must keep:
- Every screen opens with a one-sentence purpose box (what this screen is for), plus one plain-language "why" line.
- Three pillars everywhere: Onboard, Watch, Prove. The rail is grouped by them.
- Palette: navy rail 122034, teal accent 0B6E8E, amber B9792B, red B23A32, purple 7A3E9D (the deck theme). Light and dark themes via tokens.
- Fonts: Public Sans (body) and JetBrains Mono (code/ids). Both OFL. Vendored as woff2 under `src/supervisor/console/static/fonts/`; no CDN at the bank.
- Status is a coloured pill with a word, never colour alone. Numbers are tabular.
- The one action a user can take is next to the thing it acts on, with the rule for it written under the button (two-person resume, two sign-offs to close critical).
- Demo data is labelled on screen. The gate block, the pause and the chain break are always real.
