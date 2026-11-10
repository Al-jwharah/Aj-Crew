# Aj Crew brand kit

Every piece of Aj Crew artwork is generated from one definition of the gem, so
the app icon, the tray glyph, the installer art, the splash and the in-app
character cannot drift apart. Change the definition here and rebuild; do not
hand-edit the generated files.

| File | What it holds |
| --- | --- |
| `mark.py` | The gem mark: six facets on a 1024 canvas. |
| `mascot.py` | The gem character (the mark with eyes), its poses, and the 24 px line marks. |
| `petclips.py` | The desktop pet's gem pack: four Lottie clips built from the same cut. |
| `retint.py` | Moves violet, indigo and purple artwork into the accent's hue (the app catalogue's banners). |
| `textpath.py` | Turns the wordmark into outlines, so no asset needs a font installed. |
| `build.py` | Writes every asset into the checkout. |
| `eye-centers.json` | Where each avatar pose's eyes sit; `website/src/lib/avatarPoses.ts` mirrors it. |

## Rebuild

```sh
python -m pip install fonttools uharfbuzz pillow
cd website && npm ci && npx playwright install chromium && cd ..
AJ_BRAND_FONT=/path/to/Sora.ttf python scripts/brand/build.py .
```

The wordmark is set in [Sora](https://github.com/sora-xor/sora-font) (SIL Open
Font License 1.1). The font is not checked in: download the variable font and
point `AJ_BRAND_FONT` at it, or drop it next to `build.py` as `Sora.ttf`. Set
`CHROMIUM` to a Chromium binary to use one other than Playwright's own, and
`NODE` to pick the Node executable.

A rebuild with no change to the kit leaves the checkout byte-identical.

## What it writes

- `website/electron/`: `icon.png`, `icon.icns`, `icon.ico` and their `-nightly`
  twins, `build/icons*/`, `trayTemplate.png` and `trayTemplate@2x.png`, and the
  gem inside `loading.html` (the `GEM_SVG` block).
- `packaging/installer-assets/`: the disk-image background and the Windows
  installer sidebar and header, as SVG sources and their TIFF and BMP rasters.
- `website/public/icon-192.png` and `icon-512.png`, `src/aj_crew/static/ajcrew-logo*.png`,
  `site/public/ajcrew-logo.{svg,png}`, `assets/banner.svg`.
- `website/src/assets/`: `aj-mark.svg`, `aj-gem.svg`, `aj-gem-figure.svg`,
  `crew-member-mark.svg`, `avatarPoses/`, `ghost-poses/`, `onboarding/aj-gem-*.svg`,
  `aj-file-chomper.png`.
- The character's other bodies (the file and symbol names predate the gem):
  `website/src/apps/crew-companion/assets/kiro_idle.svg` (the desktop companion's
  eyeless body), the `KIRO_GHOST_PIXELS` bitmap in `website/src/hooks/sceneText.ts`
  (the canvas scenes), `website/src/apps/mochi/assets/animations/kiro_*.json` (the
  desktop pet's gem pack), and in `website/public/app-assets/crew-companion/` the
  `icon.svg` and the figure between the `companion` comments of both banners.

The crew sprite sheet in `website/src/apps/issue-radar/components/` is drawn from
that bitmap by its own generator (`crew-ghost-sprite.gen.mjs`); re-run it after
changing `PIXEL_GEM`.

`retint.py` is not part of the build. Run it by hand on artwork drawn against the
old purple theme (`python scripts/brand/retint.py website/public/app-assets`); a
second run changes nothing.

## Palette

| Role | Value |
| --- | --- |
| Ink (ground) | `#0B0C0F` |
| Paper | `#F4F5F7` |
| Accent | `#2DD4BF` on dark, `#0F766E` on light |
| Nightly accent | `#FBBF24` |
| Facets | `#FFFFFF`, `#E3E6EB`, `#BFC5CE`, `#AEB5C0`, `#8E96A3` |
| Avatar brand tile | `#30343C` |

The default `aj` theme uses the same ink and accent
(`website/src/styles/theme-palettes.css`).
