# Overflow-Clipped Descendants Evidence

Fixture: the 1600x900 showcase slide. The blue card has `overflow:hidden` and two decorative
circles that deliberately extend past its bottom-right corner.

`overflow` on an ancestor was not handled anywhere in extraction, so a child that pokes out of a
clipping parent was emitted as a native shape and drew its clipped-off part on the slide. PowerPoint
never clips one shape to another, so there is no native representation of the clip.

The snapshot now tests each element's real (possibly rotated) quad against the padding box and
corner radii of the ancestors that actually clip it, following the CSS containing-block chain: an
absolutely positioned child escapes the clips of unpositioned ancestors, `position:fixed` escapes
all of them, and a clip that already covers the whole slide is just the slide edge. A clipped
element is rasterised in isolation; the isolated capture keeps the ancestor's clip, so the layer
holds exactly the visible pixels. Contained children stay native and editable.

| Source (Chrome) | Before (`main`, LibreOffice) | After (this PR, LibreOffice) |
|---|---|---|
| ![Source](source-crop.png) | ![Before](before-main-crop.png) | ![After](after-crop.png) |

Full slides: [source](source.png), [before](before-main.png), [after](after.png).

## Evidence

On the fixture exactly two elements (the two circles) are reported as
`clipped by an ancestor's overflow`; no other shape changes representation. Real-Chromium tests:

| Test | Asserts |
|---|---|
| `test_child_clipped_by_an_ancestor_is_rasterised_without_the_clipped_part` | raster pixels right of the clip edge are transparent (fails on `main`) |
| `test_children_inside_their_clipping_ancestor_stay_native` | no false positive inside a rounded clip |
| `test_rotated_clipping_ancestor_keeps_contained_children_native` | no false positive inside a rotated clip |
| `test_absolutely_positioned_child_escapes_an_unpositioned_clipping_ancestor` | containing-block chain respected |
| `test_shape_bleeding_past_the_slide_edge_is_not_treated_as_clipped` | slide-edge bleed stays native |

## Expected lossy behaviour (not part of this change)

A clipped child becomes a non-editable raster layer. That is the price of exact pixels: there is no
native "clip to parent". Children that merely touch a rounded clip's corner zone are also treated
as clipped, which is conservative. Shadows or glows that extend past a clip while the element box
stays inside are not detected. The glass card is still a flat image and the native title is
still ~4px offset in LibreOffice; neither is changed here.
