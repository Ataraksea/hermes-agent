---
name: frontend-development
description: "Build applications with a frontend experience"
version: 1.1.0
author: OpenAI
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [planning, design, implementation, workflow, documentation]
    related_skills: [subagent-driven-development, test-driven-development, requesting-code-review]
---

## Frontend guidance

Follow these instructions when building applications with a frontend experience:

### Build with empathy

- When working with an existing design or given a design framework in context, pay careful attention to existing conventions and ensure that what is built is consistent with the frameworks used and design of the existing application.
- Think deeply about the audience of what is being built and use that to decide what features to build and when designing layout, components, visual style, on-screen text, and interaction patterns. Using the application should feel rich and sophisticated.
- Make sure that the frontend design is tailored for the domain and subject matter of the application. For example, SaaS, CRM, and other operational tools should feel quiet, utilitarian, and work-focused rather than illustrative or editorial: avoid oversized hero sections, decorative card-heavy layouts, and marketing-style composition, and instead prioritize dense but organized information, restrained visual styling, predictable navigation, and interfaces built for scanning, comparison, and repeated action. A game can be more illustrative, expressive, animated, and playful.
- Make sure that common workflows within the app are ergonomic, efficient, and comprehensive, so users can seamlessly navigate in and out of different views and pages in the application.

### Design instructions

- Use icons in buttons for tools, swatches for color, segmented controls for modes, toggles/checkboxes for binary settings, sliders/steppers/inputs for numeric values, menus for option sets, tabs for views, and text or icon+text buttons only for clear commands (unless otherwise specified). Cards are kept at 8px border radius or less unless the existing design system requires otherwise.
- Do not use rounded rectangular UI elements with text inside if a familiar symbol or icon could be used instead (examples include arrow icons for undo/redo, B/I icons for bold/italics, save/download/zoom icons). Build tooltips which name/describe unfamiliar icons on hover.
- Use lucide icons inside buttons whenever one exists instead of manually-drawn SVG icons. If there is a library enabled in an existing application, use icons from that library.
- Build feature-complete controls, states, and views that a target user would naturally expect from the application.
- Do not use visible, in-app text to describe the application's features, functionality, keyboard shortcuts, styling, visual elements, or how to use the application.
- Avoid making a landing page unless absolutely required; when asked for a site, app, game, or tool, build the actual usable experience as the first screen, not marketing or explanatory content.
- When making a hero page, use a relevant image, generated bitmap image, or immersive full-bleed interactive scene as the background with text over it that is not in a card; never use a split text/media layout where a card is one side and text is on another side, never put hero text or the primary experience in a card, never use a gradient/SVG hero page, and do not create an SVG hero illustration when a real or generated image can carry the subject.
- On branded, product, venue, portfolio, or object-focused pages, the brand/product/place/object must be a first-viewport signal, not only tiny nav text or an eyebrow. Hero content must leave a hint of the next section's content visible on every mobile and desktop viewport, including wide desktop.
- For landing-page heroes, make the H1 the brand/product/place/person name or a literal offer/category; put descriptive value props in supporting copy, not the headline.
- Websites and games must use visual assets. Prefer image search, known relevant images, or generated bitmap images instead of SVGs, unless making a game. Primary images and media should reveal the actual product, place, object, state, gameplay, or person; refrain from dark, blurred, cropped, stock-like, or purely atmospheric media when the user needs to inspect the real thing. For highly specific game assets, use custom SVG/Three.js/etc.
- For games or interactive tools with well-established rules, physics, parsing, or AI engines, use a proven existing library for the core domain logic instead of hand-rolling it, unless the user explicitly asks for a from-scratch implementation.
- Use Three.js for 3D elements, and make the primary 3D scene full-bleed or unframed and not inside a decorative card/preview container. Before finishing, verify with Playwright screenshots and canvas-pixel checks across desktop/mobile viewports that it is nonblank, correctly framed, interactive/moving, and that referenced assets render as intended without overlapping.
- Do not put UI cards inside other cards. Do not style page sections as floating cards. Only use cards for individual repeated items, modals, and genuinely framed tools. Page sections must be full-width bands or unframed layouts with constrained inner content.
- Do not add discrete orbs, gradient orbs, or bokeh blobs as decoration or backgrounds.
- Make sure that text fits within its parent UI element on all mobile and desktop viewports. Move it to a new line if needed, and if it still does not fit inside the UI element, use dynamic sizing so the longest word fits. Text must also not occlude preceding or subsequent content. Despite this, check that text inside a UI button/card looks professionally designed and polished.
- Match display text to its container: reserve hero-scale type for true heroes, and use smaller, tighter headings inside compact panels, cards, sidebars, dashboards, and tool surfaces.
- Define stable dimensions with responsive constraints (such as aspect-ratio, grid tracks, min/max, or container-relative sizing) for fixed-format UI elements like boards, grids, toolbars, icon buttons, counters, or tiles, so hover states, labels, icons, pieces, loading text, or dynamic content cannot resize or shift the layout.
- Do not scale font size with viewport width. Letter spacing must be 0, not negative.
- Avoid one-note palettes: steer clear of UIs dominated by variations of a single hue family, and limit dominant purple/purple-blue gradients, beige/cream/sand/tan, dark blue/slate, and brown/orange/espresso palettes; scan CSS colors before finalizing and revise if the page reads as one of these themes.
- Make sure that UI elements and on-screen text do not overlap with each other in an incoherent manner. This is extremely important because overlap can lead to a jarring user experience.

When building a site or app that needs a dev server to run properly, start the local dev server after implementation and give the user the URL to try it. If there's already a server on that port, use another one. For a website where just opening the HTML will work, skip the dev server, and instead give the user a link to the HTML file that can open in their browser.