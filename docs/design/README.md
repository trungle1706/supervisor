# Console design reference (2026-10-15)

`console-prototype.html` is the approved look and information architecture for the reviewer console (WP12 rebuild). Open it in a browser; the left rail switches screens. The PNGs are reference renders at 1360x900.

Design rules the real console must keep:
- Every screen opens with a one-sentence purpose box (what this screen is for), plus one plain-language "why" line.
- Three pillars everywhere: Onboard, Watch, Prove. The rail is grouped by them.
- Shell per the owner's reference (`owner-reference.jpg`): top pill navigation, greeting on the home screen, airy rounded cards (radius 18) on a soft gradient, dark rounded badges, pill tabs on detail pages.
- Palette: Techcombank brand red (prototype uses E4002B; replace with the brand guide value) as the single primary, charcoal ink 141414, warm white F4F4F2, white cards; gold B58B2A only for evidence/signatures; green/amber/red soft tints for status. Light and dark themes via tokens.
- Fonts: Plus Jakarta Sans (body) and JetBrains Mono (code/ids). Both OFL. Vendored as woff2 under `src/supervisor/console/static/fonts/`; no CDN at the bank.
- Status is a coloured pill with a word, never colour alone. Numbers are tabular.
- The one action a user can take is next to the thing it acts on, with the rule for it written under the button (two-person resume, two sign-offs to close critical).
- Demo data is labelled on screen. The gate block, the pause and the chain break are always real.
