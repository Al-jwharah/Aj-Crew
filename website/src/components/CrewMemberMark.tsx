// The Crew Member mark: two Aj Crew gems, a large one with a small one beside
// it, sized and tinted for use as the `/members` nav glyph.
//
// Why this is an ASSET and not a Lucide glyph: what the rail needs to say here
// is "the named Aj crew members you hold conversations with", and the half of
// that which carries the meaning is the GEM. lucide-react ships no brand marks,
// so there is nothing to compose the pair from. This is the same gap `AjMark`
// already fills on this rail, under the `use-lucide-icons` BRAND-MARK EXCEPTION
// (`website/AUTOSDE.yaml`). The layout says "members, plural" the way Lucide's
// own `Users` does (a full figure, and a second smaller one beside it); the gem
// is what makes them Aj Crew's.
//
// The exception's three conditions are met the way the in-tree precedents meet
// them: the art lives in its own `.svg` under `src/assets/` and is consumed
// through a plain URL import (no `<svg>` element or path data in any `.tsx`;
// the regex gate blocks that unconditionally); it is monochrome, so it is
// painted as a CSS `mask` over `currentColor` via the shared `BrandGlyph`
// helper rather than a fixed-colour `<img>`, which is what lets it follow the
// rail's active (accent) / idle (muted) colour states and every theme's palette;
// and the identity it depicts is the product's own mark.
//
// GEM GEOMETRY: the large gem keeps only its outline and girdle line, the small
// one only its outline. The inner facet lines `AjMark` draws were tried at this
// scale and close up at the rail's 16px on a 1x display; the two silhouettes
// are the cue that survives that size. The two never touch: the clear gap
// between them is what reads as "two stones" rather than one knot.
//
// STROKE WEIGHT: the asset is drawn on a 24×24 viewBox at `stroke-width="2"`,
// byte-for-byte Lucide's own geometry contract, so at the rail's `size={16}` it
// scales to the same 1.33px optical stroke as the `size={16}` Lucide glyphs it
// sits beside. `test/CrewMemberMark.test.tsx` pins both numbers in the asset,
// because editing either one silently makes this glyph heavier or lighter than
// every one of its neighbours and nothing else in the build would notice.
// `scripts/brand/` generates the file.
import { BrandGlyph } from './BrandIcon'
import crewMemberMarkUrl from '../assets/crew-member-mark.svg'

/**
 * Crew Member brand glyph: the two-gem pair.
 *
 * @param size  Box edge in px; the mark is aspect-fit inside it (default 16,
 *              matching the `size={16}` Lucide glyphs in the nav rail).
 */
export function CrewMemberMark({ size = 16, className = 'inline-block shrink-0' }: { size?: number; className?: string }) {
  return <BrandGlyph url={crewMemberMarkUrl} size={size} className={className} testId="crew-member-mark" />
}
