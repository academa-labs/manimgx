---
hide:
  - navigation
---

# Changelog

The notable changes to ManimGX, release by release. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and ManimGX follows
[Semantic Versioning](https://semver.org/).

<!--
### Added
### Changed
### Fixed
### Removed
-->

## Unreleased

### Added

- Add a preview image and social metadata when sharing website and documentation links.
- Credit Academa and the creators in the README.
- Add Manim CE's `partial_bezier_points`, `subdivide_bezier`, `bezier_remap`, `integer_interpolate`, `is_closed` and `get_smooth_cubic_bezier_handle_points` to the package.
- Add `remove_fixed_in_frame_mobjects` to `ThreeDScene` and `Camera`, Manim CE's undo of `add_fixed_in_frame_mobjects`: the camera moves the mobjects again.
- Add `get_height()`, deprecated in favor of `height`, as `get_width()` is in favor of `width`: Manim CE scenes call both.

### Changed

- Use ordinary attribute suggestions for CLI name mistakes instead of a table of unsupported legacy names.
- Store encoded speech-cache bytes without guessing their file extension; decoding still uses their contents.
- Load optional network, SVG, typesetting, contour and window dependencies only when their features need them.
- Draw a surface rebuilt every frame in half the time (the benchmark's rippling surface): its spline's derivatives and its patches are matrix products over all its cells side by side, and its faces are gathered once. The frames are the same.
- Render faster: a graph's area reads its points' coordinates all at once, colors mix without numpy's overhead and are converted to OKLab once, and a family is listed in one pass. The frames are the same.
- Draw and encode a film's frames on a thread of their own: the scene's Python no longer waits for the GPU or the encoder, but for the pixels it asks for and its video's end. The videos are the same.
- Hold the API to its declared types, which ty checks where it is called: `add`, `ApplyFunction`, `SurroundingRectangle`, `ArcPolygonFromArcs` and `voices.Fal` no longer check them again as they run, and an `Animation` always has a mobject (`Wait` and a sound pass a plain `Mobject()`, where `None` stood). `interpolate` is typed by what it mixes (numbers, complex numbers or arrays), and `midpoint`, `center_of_mass`, `bezier`, `partial_bezier_points`, `subdivide_bezier` and `bezier_remap` by the array-likes they take (and `subdivide_bezier`'s count by numpy's integers too).
- Show measured render times in a static benchmark chart.
- Use a Markdown table for the benchmark comparison images.
- Install ManimGX in the Quickstart with one command, `pip install manimgx`, and run `manimgx` directly throughout the docs.
- Move the benchmark to `benchmarks/`, whose README explains its scenes, method and results; the README's numbers link to it.
- Arrange the Rendering and sharing page by command, with settings, tall videos and rendering from Python under Render.
- Make `become` give a mobject another's value, member by member: each member takes its counterpart's points, shape and whole style (its joint and cap styles and 3D shading too), and stays itself, updaters and all, where the other has a member drawn as it is in its place; the members it gains come without updaters, and those it has beyond the other's go. What it was never shows through, becoming the same value again changes nothing, the other is left as it was, and a mobject can become itself or one of its own members. A group or a point cloud that becomes a shape holds the shape in a first member. It is faster too.
- End a transform as its target: its mobject becomes the keyframe its last frame shows, so the points and parts its frames gained on the way never outlive it. A morph that follows another starts from the shape the first ended on, not from that shape divided as the first needed it; `Restore` brings back exactly what was saved, and a remover leaves its mobject as it was. Transforms played together on one mobject still compose. Films that chain morphs change slightly.
- Play `TransformFromCopy` forward: the target turns from the mobject's copy into itself as any transform does, its rate function, `path_arc` and `lag_ratio` running from the copy to the target (they ran backward, the arcs bending the other way), and it ends exactly as itself.
- Take NumPy out of the package: a scene imports it itself (`import numpy as np`), and `from manimgx import *` no longer brings `np`.
- Make the voices' names the package's, as every other name is: `m.Fal`, `m.Voice`, `m.Word`, `m.timed`, `m.estimate` and `m.cached`, where they were `m.voices.Fal` and `manimgx.audio.Voice`. `m.voices` is gone.
- Compute every play frame by frame, one way. A play of transforms alone was computed ahead of time, its frames mixed from its keyframes' drawn records, and those could differ from the play computed frame by frame (a sheared cube shaded otherwise, a gradient mixed into itself). A part waiting at one progress (a letter of a `Write` before its turn) is not computed again while nothing it reads changes, so a long text is written about as fast as before, and a play of many staggered parts faster.
- Animate many parts faster, one frame at a time: a tween's path works out its rule once a frame for all the parts it moves, a paint mix is the first paint with only what differs from the second mixed (what differs found once for the two), parts whose paints are the same share one mix, and a play finds the windows of its parts that open or close before a frame by bisection. A group of 400 dots turned and recolored takes a third of the time. A paint mixed so near its end that the player draws the end is recorded as the end, so the film holds that frame rather than drawing it again. The frames are the same.
- Run the updaters of a mobject an animation plays on on the mobject itself, beneath the animation, which shows itself over what they make of it (while it suspends their updating, as it does by default). They ran on a copy, so what they keep (an `AnimatedBoundary`'s time, a stream line's phase, an animation turned into an updater) went back where it was when the play ended, and an `AnimatedBoundary` outlined its mobject as it was before the play.
- Compose animations played together on one mobject: each adds its change to the mobject's own value, moves carried one by the other, each paint field the last changer's. A shift and a turn of one square end where applying them in turn puts it, whatever their order, and one that ends first goes on showing its end until the last ends. A group's animation carries what its members' own animations do: a group turned or scaled while a member moves shows the member moved, turned or scaled with the group.
- Turn `always_rotate`'s mobject about its center of mass, not its bounding box's center: a turn about it keeps the mobject where it is, so it turns the same at every frame rate (a 3-4-5 triangle's box center moves as it turns).
- Make `UpdateFromFunc` and `MaintainPositionRelativeTo` relations: they act once a frame, and at their play's end, after the frame's other animations and the updaters that take time, whatever order the play lists them in.
- Draw a typeset rule (a fraction's bar, a radical's vinculum, a box's outline) as the shape it covers, filled, as Manim CE's LaTeX does: it scales with its formula under every map (a formula scaled alone or within a group shows the same bar), and `Write` draws its outline, then fills it. `Typst` no longer overrides `scale` to rescale such strokes.
- Make a scale by 1 change nothing (an arrow still sets its stroke width from its length) and a turn by 0 no turn: a play of either shows its mobject as it is, to the bit, as a wait does.
- Name the settings' module `manimgx.settings`. `manimgx.config` is the settings themselves, as `m.config` is: after `import manimgx.config`, `manimgx.config.Config` failed.

### Fixed

- Number a line's ticks with the decimal places they need: a range on one side of 0 that starts between whole numbers, such as `NumberLine((3.5, 7.5, 1))`, was numbered 4, 4, 6, 6, 8, where its ticks are at 3.5, 4.5, …; a step written with an exponent (`1e-05`) gave no places, and one with round-off (`0.1 + 0.2`) gave 17.
- Show the world at an instant the same at every frame rate. Each part of a play begins and ends at its own window, whether a frame falls there or not, and reads what the parts before it did by then; a simulated updater added during a play steps on the simulation clock; a `ChangeSpeed` of a `Wait` in a `Succession` lasts its own time; two animations on one mobject, one of which reshapes it (a transform into dots), compose from their first frame; and a stream line flow ends at one instant.
- Join a graph's edges, and a polyhedron's faces, to a vertex that one animation moves while another moves, turns, scales or recolors the whole graph in the same play: they joined it where it was before the play.
- Keep an animation an updater plays (`turn_animation_into_updater`, `cycle_animation`) from folding the other animations playing on its mobject into it, once an instant.
- Restart a cycling animation an updater plays (`cycle_animation`) exactly where each cycle ends, whatever instants the scene computes between frames: its time, taken from steps rounded to floats, fell short of the end by a hair, and the frame there showed the cycle's end.
- Copy a `ChangeSpeed` updater with a clock of its own: the copy ran on the original's, at its speed.
- Run the updaters of a member shared by two groups of one family once an instant, not once a group.
- Count a replacement's time from when `Scene.replace` puts it in the scene: its first step was the time since it was made.
- Call an `UpdateFromFunc` once a frame, whatever else the scene holds: with a `TracedPath` in the scene, it ran again at the simulation clock's ticks.
- Move `MoveAlongPath`'s mobject along its path as the path is at each frame (another part of the play may move it), and on past its ends where the rate function overshoots.
- Follow a transform's target that moves from when the transform begins, at every frame, whether its updaters are the scene's to run or the transform's (a target the scene does not hold). A target the scene moved was read only when the mobject's own updaters made the transform derive its keyframes again, and then before the target had moved at that instant: the frames depended on the frame rate, and the mobject did not end on the target.
- Outline the parts a mobject has now with `AnimatedBoundary`: when its mobject lost parts (a transform that ends as its target, a part removed), the outlines of the parts it no longer had stayed drawn, as they were at whichever instant it last had them, so what showed depended on the instants the scene computed.
- Move the members plays hold with their group's updater: a group drifting while a `LaggedStartMap` faded its members in left each member where its part began, as the plays wrote over what the updater did to it, so the film also depended on the frame rate. A part that begins between frames reads what a group's updater has moved by then.
- Move what plays hold with any updater: a square that the scene's own updater (`self.add_updater`) or another mobject's updater carried stood still while a play recolored it, the play's frames writing over what the updater did, and a play that changed nothing of it was not a wait.
- Keep no paint a mobject no longer has: a mobject repainted at every frame (an updater turning or recoloring it) kept every paint it had alive, each remembered by the one before it, and copying what still held its first could recurse too deep.
- Animate a light's intensity, radius, angle, softness and where a spot points (`toward`) with `.animate.set(...)`, and take them with `become`, which takes all a light is read by: its color, whether it casts shadows and an environment's picture too.
- Point a line's tips along it at both its ends in space: the start tip of a line in space pointed off it.
- Leave the mobject a `Brace` braces exactly as it was (it turned it and back, changing its last bits), and brace an arc where it is with `ArcBrace`: after the arc turned or moved, its brace was where the arc had been made.
- Refine gradient stops when aligning paints, turn sheen directions with animated motions, and preserve geometry and its length fractions through self-mixes and similarity placements.
- Run each preview generation in a fresh, pre-started process so edits cannot retain earlier class defaults or other library state.
- Load scene files under private names without replacing imported modules.
- Sample every scene at the frame rate its film fixed when rendering began.
- Clip sound before the film starts instead of mixing it at the end.
- Name function voices by readable source and include partial arguments, mapping settings and inherited slots in their cache identities; generated voices without source need explicit dataclass settings.
- Store only digests of voice identities so committed speech records contain no voice credentials or settings.
- Speak a line again when its cached recording or metadata is missing or unreadable.
- Allow frame width and both frame radii to be set while preserving the video proportions.
- Start animations in empty speech spans at their position, including speech with no words.
- Keep subtitle cues within the film, omit captions outside it and normalize empty lines in subtitle text.
- Transform between paths, point clouds, meshes and non-drawing values, including empty families, without mixing incompatible geometry domains.
- Keep alignment fillers and animation keyframes free of updaters and saved history, begin from the source before alignment, and refresh recorded targets at the current instant.
- Exclude non-drawing trackers from family bounds, keep saved states and targets from nesting, and preserve a double arrow's stroke under an identity scale.
- Carry sheen directions consistently through affine maps and allow sheen on an empty point cloud.
- Refresh gradient bounds and image sampling after edits, and hold equal paints without mixing them.
- Give a type checker the package's names: each module lists the names it gives in `__all__`, and each package takes in its children's and gathers their lists, so `m.Scene`, `m.Text`, `m.config` and every other name are the package's, where they were reported as not exported ([#38](https://github.com/academa-labs/manimgx/issues/38)). `from manimgx import *` binds exactly those names, no longer the package's modules too: `manimgx.typing` took the place of the standard library's `typing`.
- Redraw a shape that empties with `always_redraw` without a RecursionError, and keep a mobject's updaters off the member its points move into when a transform aligns it, so a relative updater such as `always_shift` no longer runs twice on them ([#32](https://github.com/academa-labs/manimgx/issues/32)).
- Measure a text's size in `inspect` and `render` at 1080p, which is 1080 px on a video's short side, so a tall video (1080x1920) no longer reports readable text as small ([#37](https://github.com/academa-labs/manimgx/issues/37)).
- Make the folder a video or a storyboard is written in when it is missing (`render -o new/out.mp4`, `inspect -o new/sheet.png` and `Scene.render`), instead of failing with "No such file or directory" ([#34](https://github.com/academa-labs/manimgx/issues/34)).
- Raise a ValueError, naming where it is, for a nested, unclosed or stray bracket in a `say` script, which was spoken and captioned ([#39](https://github.com/academa-labs/manimgx/issues/39)).
- Time and caption speech in the pieces Unicode lets a line break between, so a `say` span in Chinese, Japanese or Thai, written without spaces, is timed by its own characters or words, where the whole sentence was one word ([#40](https://github.com/academa-labs/manimgx/issues/40)). Captions are the text as it is written, at most 42 columns wide (a Chinese or Japanese character takes two); a line never starts with a closing mark such as `，` or `」`, and ends where a sentence does, a quoted one too. A speech's words are found in its text by themselves, so a trimmed speech, or a voice that cuts its words its own way, no longer fails or mistimes a span; and an empty span after the last word starts where that word ends.
- Show an image drawn smaller than its pixels as their mean: each pixel of the video shows the mean of the picture's pixels it covers, however the image is squashed and whatever its `resampling_algorithm`, where it showed the picture at one point, so thin lines broke up and small text was unreadable ([#36](https://github.com/academa-labs/manimgx/issues/36)). An image at its size or larger is drawn as before.
- Trace a `TracedPath` once at each instant, and on while a play animates it. Where the scene came to an instant again (one play's end is the next one's beginning), the path recorded the point a second time, as a curve of no length. A play of the path traced a frozen copy of the traced mobject, a tick late, and lost when the curves were traced: the path stood still through the play and jumped at its end, and a dissipating one kept curves too long. A dissipating path's curves age in scene time, also while it is out of the scene. Paths that grow alike are uploaded once, as equal shapes are, where each copy uploaded every curve it gained.
- Write the same take of a scene however often it is made: the view of a camera shown as a picture (an `ImageMobjectFromCamera`'s) was named by the camera's address in memory, so two takes of one scene differed, and a play that changes nothing on such a picture filmed otherwise than a wait.
- Keep resources needed by queued video frames until their transparency retries finish, fixing render failures during cache cleanup ([#16](https://github.com/academa-labs/manimgx/issues/16)).
- Draw a storyboard picture without dropping the frame the film holds back, fixing `manimgx render` failures ("unknown shape") under memory pressure.
- Draw a vectorized curve whose function gives a component as one number (`use_vectorized` with `lambda t: (t, t**2, 0)`), which failed with numpy's inhomogeneous-shape error.
- Name a partite layout's vertex that is not in the graph, and a vertex's keywords or an edge's `tip_config` that are not a mapping, in the error raised.
- Preserve the benchmark comparison images' aspect ratios when PyPI narrows the README table.
- Credit Filament, whose code the 3D lighting is adapted from, in the README and the wheels' third-party notices.
- End a `{{…}}` part of a `MathTex` or `Tex` at the `}}` that closes its own braces: `MathTex(r"V={{\tfrac{1}{3}}}B")` split at the fraction's `}}`, so the part was `\tfrac{1}{3` and `get_part_by_tex(r"\tfrac{1}{3}")` found nothing. An escaped brace (`\{` or `\}`) no longer opens or closes a part.

### Removed

- Remove `Transform.moving_target`, ManimGX's own machinery: a transform follows every target that moves, whoever runs its updaters, so nothing asks which ones it runs itself.

## 0.1.1

### Changed

- Updated package author metadata to Academa Team. The font packages have metadata-only post-releases; their font files are unchanged.

### Fixed

- Fixed GPU validation failures when meshes with materials share a scene with ordinary meshes, overlays, or point sprites, including during fades.

## 0.1.0

First release of ManimGX.
